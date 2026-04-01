from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .llm_client import LLMReply, OllamaClient
from .memory_manager import MemoryManager


IGNORED_PREFIXES = {
    ".deepsleep",
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


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

    def record_change(self, file_path: str, event_type: str = "modified") -> bool:
        relative = self._to_relative(file_path)
        if relative is None or self._should_ignore(relative):
            return False

        self.pending_changes[relative] = time.time()
        self.last_activity_at = time.time()
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
        previous_summary = self.memory_manager.load()["session"]["summary"]
        reply = self.llm_client.summarize_activity(changed_files, snippets, previous_summary)
        self.memory_manager.record_dream(reply.text, changed_files, reply.model)
        self.pending_changes.clear()
        return reply

    def run_forever(self) -> None:
        observer = Observer()
        handler = _DreamEventHandler(self)
        observer.schedule(handler, str(self.project_root), recursive=True)
        observer.start()
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
        now = time.time()
        recent_paths: List[tuple[str, float]] = []

        for candidate in self.project_root.rglob("*"):
            if not candidate.is_file():
                continue

            try:
                relative = str(candidate.relative_to(self.project_root))
            except ValueError:
                continue

            if self._should_ignore(relative):
                continue

            try:
                modified_at = candidate.stat().st_mtime
            except OSError:
                continue

            if now - modified_at <= self.snapshot_window_seconds:
                recent_paths.append((relative, modified_at))

        recent_paths.sort(key=lambda item: item[1], reverse=True)
        return [path for path, _ in recent_paths[:6]]

    def _should_ignore(self, relative_path: str) -> bool:
        first_segment = Path(relative_path).parts[0] if Path(relative_path).parts else relative_path
        return first_segment in IGNORED_PREFIXES

    def _to_relative(self, file_path: str) -> Optional[str]:
        try:
            return str(Path(file_path).resolve().relative_to(self.project_root))
        except ValueError:
            return None
