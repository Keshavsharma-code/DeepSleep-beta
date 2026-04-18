from __future__ import annotations

import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

from .llm_client import LLMReply, OllamaClient
from .memory_manager import MemoryManager

logger = structlog.get_logger()

IGNORED_PREFIXES = {
    ".deepsleep",
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


@dataclass
class FileIndex:
    """SQLite-based index for efficient file change tracking."""
    db_path: Path
    
    def __post_init__(self) -> None:
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                last_checked TIMESTAMP
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_mtime ON files(mtime)")

    def get_recent_files(self, since: float, limit: int = 20) -> List[str]:
        cursor = self.conn.execute(
            "SELECT path FROM files WHERE mtime > ? ORDER BY mtime DESC LIMIT ?",
            (since, limit)
        )
        return [row[0] for row in cursor.fetchall()]

    def update(self, path: str, mtime: float, size: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO files (path, mtime, size, last_checked) VALUES (?, ?, ?, ?)",
            (path, mtime, size, datetime.now().isoformat())
        )
        self.conn.commit()


class _DreamEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "DreamWatcher") -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        path = getattr(event, "dest_path", "") or event.src_path
        self.watcher.record_change(path, event.event_type)


class DreamWatcher:
    """Watches a project and writes a new session summary after idle time."""

    def __init__(
        self,
        project_root: Path,
        memory_manager: MemoryManager,
        llm_client: OllamaClient,
        idle_seconds: int = 300,
        poll_seconds: float = 1.0,
        snapshot_window_seconds: int = 1800,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self.idle_seconds = idle_seconds
        self.poll_seconds = poll_seconds
        self.snapshot_window_seconds = snapshot_window_seconds
        self.pending_changes: Dict[str, float] = {}
        self.last_activity_at = time.time()
        
        # P1: Incremental Indexing
        self.index = FileIndex(self.project_root / ".deepsleep" / "index.db")
        self.gitignore_spec = self._load_gitignore()

    def _load_gitignore(self) -> PathSpec:
        gitignore = self.project_root / ".gitignore"
        if gitignore.exists():
            try:
                patterns = gitignore.read_text(encoding="utf-8").splitlines()
                return PathSpec.from_lines(GitWildMatchPattern, patterns)
            except Exception as exc:
                logger.warning("gitignore_load_failed", error=str(exc))
        return PathSpec.from_lines(GitWildMatchPattern, [])

    def record_change(self, file_path: str, event_type: str = "modified") -> bool:
        relative = self._to_relative(file_path)
        if relative is None or self._should_ignore(relative):
            return False

        now = time.time()
        self.pending_changes[relative] = now
        self.last_activity_at = now
        
        # Update index
        try:
            target = self.project_root / relative
            if target.exists():
                stat = target.stat()
                self.index.update(relative, stat.st_mtime, stat.st_size)
        except Exception:
            pass

        self.memory_manager.record_file_event(relative, event_type)
        return True

    def dream_once_if_idle(self, force: bool = False) -> Optional[LLMReply]:
        if not self.pending_changes and force:
            for relative_path in self._discover_recent_files():
                self.pending_changes[relative_path] = time.time()

        if not self.pending_changes:
            return None

        idle_for = time.time() - self.last_activity_at
        if not force and idle_for < self.idle_seconds:
            return None

        changed_files = sorted(self.pending_changes.keys())
        snippets = self._collect_snippets(changed_files)
        memory = self.memory_manager.load()
        previous_summary = memory["session"]["summary"]
        
        logger.info("dream_start", files=len(changed_files))
        reply = self.llm_client.summarize_activity(changed_files, snippets, previous_summary)
        self.memory_manager.record_dream(reply.text, changed_files, reply.model)
        
        self.pending_changes.clear()
        return reply

    def run_forever(self) -> None:
        observer = Observer()
        handler = _DreamEventHandler(self)
        observer.schedule(handler, str(self.project_root), recursive=True)
        observer.start()
        logger.info("watcher_started", root=str(self.project_root))
        try:
            while True:
                self.dream_once_if_idle()
                time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()

    def _collect_snippets(self, changed_files: List[str]) -> Dict[str, str]:
        snippets: Dict[str, str] = {}
        for relative_path in changed_files[:6]:
            candidate = self.project_root / relative_path
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            snippets[relative_path] = text[:1200]
        return snippets

    def _discover_recent_files(self) -> List[str]:
        # Try git ls-files first for speed
        git_files = self._try_git_ls_files()
        if git_files:
            return git_files[:6]

        # Fallback to index or rglob
        now = time.time()
        since = now - self.snapshot_window_seconds
        indexed = self.index.get_recent_files(since, limit=10)
        if indexed:
            return [f for f in indexed if not self._should_ignore(f)][:6]

        recent_paths: List[tuple[str, float]] = []
        for candidate in self.project_root.rglob("*"):
            if not candidate.is_file():
                continue

            relative = self._to_relative(str(candidate))
            if relative is None or self._should_ignore(relative):
                continue

            try:
                modified_at = candidate.stat().st_mtime
                if now - modified_at <= self.snapshot_window_seconds:
                    recent_paths.append((relative, modified_at))
            except OSError:
                continue

        recent_paths.sort(key=lambda item: item[1], reverse=True)
        return [path for path, _ in recent_paths[:6]]

    def _try_git_ls_files(self) -> Optional[List[str]]:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-files", "--modified", "--others", "--exclude-standard"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                files = result.stdout.strip().split("\n")
                return [f for f in files if f and not self._should_ignore(f)]
        except Exception:
            pass
        return None

    def _should_ignore(self, relative_path: str) -> bool:
        # Check hardcoded prefixes first
        first_segment = Path(relative_path).parts[0] if Path(relative_path).parts else relative_path
        if first_segment in IGNORED_PREFIXES:
            return True
            
        # Check gitignore
        return self.gitignore_spec.match_file(relative_path)

    def _to_relative(self, file_path: str) -> Optional[str]:
        try:
            path = Path(file_path).resolve()
            relative = path.relative_to(self.project_root)
            # Normalise to forward slashes on all platforms (including Windows)
            return relative.as_posix()
        except (ValueError, RuntimeError):
            return None
