from __future__ import annotations

import copy
import json
import hashlib
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock, Timeout
from cryptography.fernet import Fernet
import structlog

from .config import DeepSleepConfig

logger = structlog.get_logger()

MAX_MEMORY_BYTES = 2048


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryManager:
    """Maintains DeepSleep's 3-layer memory in .deepsleep/memory.json with concurrency safety."""

    def __init__(self, project_root: Path, config: Optional[DeepSleepConfig] = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.config = config or DeepSleepConfig.load_from_project(self.project_root)
        self.state_dir = self.project_root / ".deepsleep"
        self.memory_path = self.state_dir / "memory.json"
        self.activity_log_path = self.state_dir / "activity.jsonl"
        self.chat_history_path = self.state_dir / "prompt_history.txt"
        self.lock_path = self.state_dir / ".memory.lock"
        self.lock = FileLock(str(self.lock_path), timeout=5)
        self.max_bytes = self.config.memory.max_bytes

    def initialize(self, force: bool = False) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)

        with self.lock:
            if self.memory_path.exists() and not force:
                return self.memory_path

            memory = self.default_memory()
            self._write_atomic(memory)
        
        self.activity_log_path.touch(exist_ok=True)
        self.chat_history_path.touch(exist_ok=True)
        return self.memory_path

    def default_memory(self) -> Dict[str, Any]:
        timestamp = utc_now()
        return {
            "version": 1,
            "project": {
                "summary": "Project memory is empty. Capture the repo purpose here.",
                "goals": [],
                "facts": [],
            },
            "session": {
                "summary": "No session summary yet.",
                "recent_files": [],
                "recent_tasks": [],
                "last_dream_at": None,
            },
            "ephemeral": {
                "last_user_message": "",
                "last_assistant_message": "",
                "open_questions": [],
                "recent_changes": [],
            },
            "meta": {
                "project_root": str(self.project_root),
                "created_at": timestamp,
                "updated_at": timestamp,
                "byte_size": 0,
                "compacted": False,
                "last_model": "deepseek-r1",
            },
        }

    def load(self) -> Dict[str, Any]:
        try:
            with self.lock.acquire(timeout=3):
                return self._unsafe_load()
        except Timeout:
            logger.error("memory_load_timeout", path=str(self.memory_path))
            raise RuntimeError("DeepSleep is busy in another process. Retry in 3 seconds.")

    def _unsafe_load(self) -> Dict[str, Any]:
        if not self.memory_path.exists():
            return self.default_memory()

        with self.memory_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            memory = copy.deepcopy(memory)
            compacted = self._compact(memory)
            self._write_atomic(compacted)
            return compacted

    def get_status(self) -> Dict[str, Any]:
        memory = self.load()
        file_size = self.memory_path.stat().st_size if self.memory_path.exists() else 0
        return {
            "project_root": str(self.project_root),
            "memory_path": str(self.memory_path),
            "activity_log_path": str(self.activity_log_path),
            "file_size": file_size,
            "project_summary": memory["project"]["summary"],
            "session_summary": memory["session"]["summary"],
            "recent_files": memory["session"]["recent_files"],
            "last_dream_at": memory["session"]["last_dream_at"],
            "last_model": memory["meta"].get("last_model", "deepseek-r1"),
        }

    def build_context(self) -> str:
        memory = self.load()
        recent_files = ", ".join(memory["session"]["recent_files"]) or "none"
        recent_tasks = ", ".join(memory["session"]["recent_tasks"]) or "none"
        open_questions = ", ".join(memory["ephemeral"]["open_questions"]) or "none"
        recent_changes = ", ".join(memory["ephemeral"]["recent_changes"]) or "none"

        return (
            "Project layer:\n"
            f"- Summary: {memory['project']['summary']}\n"
            f"- Goals: {', '.join(memory['project']['goals']) or 'none'}\n"
            f"- Facts: {', '.join(memory['project']['facts']) or 'none'}\n\n"
            "Session layer:\n"
            f"- Summary: {memory['session']['summary']}\n"
            f"- Recent files: {recent_files}\n"
            f"- Recent tasks: {recent_tasks}\n"
            f"- Last dream at: {memory['session']['last_dream_at'] or 'never'}\n\n"
            "Ephemeral layer:\n"
            f"- Recent changes: {recent_changes}\n"
            f"- Open questions: {open_questions}\n"
            f"- Last user message: {memory['ephemeral']['last_user_message']}\n"
            f"- Last assistant message: {memory['ephemeral']['last_assistant_message']}\n"
        )

    def record_project_note(self, note: str) -> Dict[str, Any]:
        memory = self.load()
        project = memory["project"]
        project["facts"] = self._append_unique(project["facts"], self._clip(note, 180), limit=6)
        return self.save(memory)

    def record_file_event(self, relative_path: str, event_type: str) -> Dict[str, Any]:
        memory = self.load()
        labeled = f"{event_type}:{relative_path}"
        memory["ephemeral"]["recent_changes"] = self._append_unique(
            memory["ephemeral"]["recent_changes"],
            labeled,
            limit=8,
        )
        self.log_event(
            "file_event",
            {
                "path": relative_path,
                "event_type": event_type,
            },
        )
        return self.save(memory)

    def record_chat_turn(
        self,
        user_message: str,
        assistant_message: str,
        files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        memory = self.load()
        files = files or []
        memory["ephemeral"]["last_user_message"] = self._clip(user_message, 180)
        memory["ephemeral"]["last_assistant_message"] = self._clip(assistant_message, 220)
        memory["session"]["recent_files"] = self._merge_paths(memory["session"]["recent_files"], files, 6)
        memory["session"]["recent_tasks"] = self._append_unique(
            memory["session"]["recent_tasks"],
            self._clip(user_message, 140),
            limit=5,
        )
        self.log_event(
            "chat_turn",
            {
                "user": self._clip(user_message, 500),
                "assistant": self._clip(assistant_message, 500),
                "files": files,
            },
        )
        return self.save(memory)

    def record_dream(
        self,
        summary: str,
        changed_files: List[str],
        model_name: str,
    ) -> Dict[str, Any]:
        memory = self.load()
        memory["session"]["summary"] = self._clip(summary, 420)
        memory["session"]["recent_files"] = self._merge_paths(
            memory["session"]["recent_files"],
            changed_files,
            8,
        )
        memory["session"]["last_dream_at"] = utc_now()
        memory["ephemeral"]["recent_changes"] = [
            self._clip(change, 140) for change in changed_files[-8:]
        ]
        memory["meta"]["last_model"] = model_name
        self.log_event(
            "dream",
            {
                "summary": self._clip(summary, 600),
                "files": changed_files,
                "model": model_name,
            },
        )
        return self.save(memory)

    def log_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": utc_now(),
            "type": event_type,
            "payload": payload,
        }
        with self.activity_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")

    def _write_atomic(self, memory: Dict[str, Any]) -> None:
        memory = copy.deepcopy(memory)
        memory["meta"]["updated_at"] = utc_now()
        raw = self._serialize(memory)
        memory["meta"]["byte_size"] = len(raw.encode("utf-8"))
        raw = self._serialize(memory)
        
        # Write to .tmp first, then atomic rename
        tmp_path = self.memory_path.with_suffix('.tmp')
        tmp_path.write_text(raw, encoding="utf-8")
        tmp_path.replace(self.memory_path)
        logger.debug("memory_save_atomic", path=str(self.memory_path), size=memory["meta"]["byte_size"])

    def _serialize(self, memory: Dict[str, Any]) -> str:
        return json.dumps(memory, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def _compact(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        compacted = copy.deepcopy(memory)

        compacted["project"]["summary"] = self._clip(compacted["project"]["summary"], 260)
        compacted["session"]["summary"] = self._clip(compacted["session"]["summary"], 420)
        compacted["ephemeral"]["last_user_message"] = self._clip(
            compacted["ephemeral"]["last_user_message"],
            180,
        )
        compacted["ephemeral"]["last_assistant_message"] = self._clip(
            compacted["ephemeral"]["last_assistant_message"],
            220,
        )
        compacted["project"]["goals"] = self._normalize_list(compacted["project"]["goals"], 4, 90)
        compacted["project"]["facts"] = self._normalize_list(compacted["project"]["facts"], 5, 90)
        compacted["session"]["recent_files"] = self._normalize_list(
            compacted["session"]["recent_files"],
            8,
            80,
        )
        compacted["session"]["recent_tasks"] = self._normalize_list(
            compacted["session"]["recent_tasks"],
            5,
            120,
        )
        compacted["ephemeral"]["open_questions"] = self._normalize_list(
            compacted["ephemeral"]["open_questions"],
            4,
            120,
        )
        compacted["ephemeral"]["recent_changes"] = self._normalize_list(
            compacted["ephemeral"]["recent_changes"],
            8,
            120,
        )
        compacted["meta"]["compacted"] = False

        squeeze_steps = [
            lambda value: self._trim_list(value, ("ephemeral", "recent_changes")),
            lambda value: self._trim_list(value, ("session", "recent_tasks")),
            lambda value: self._trim_list(value, ("project", "facts")),
            lambda value: self._trim_string(value, ("ephemeral", "last_assistant_message"), 120),
            lambda value: self._trim_string(value, ("session", "summary"), 260),
            lambda value: self._trim_list(value, ("session", "recent_files")),
            lambda value: self._trim_string(value, ("project", "summary"), 160),
            lambda value: self._clear_list(value, ("ephemeral", "open_questions")),
        ]

        raw = self._serialize(compacted)
        if len(raw.encode("utf-8")) <= self.max_bytes:
            return compacted

        compacted["meta"]["compacted"] = True
        for squeeze in squeeze_steps:
            raw = self._serialize(compacted)
            if len(raw.encode("utf-8")) <= self.max_bytes:
                break
            squeeze(compacted)

        while len(self._serialize(compacted).encode("utf-8")) > self.max_bytes:
            if compacted["session"]["recent_files"]:
                compacted["session"]["recent_files"].pop(0)
                continue
            if compacted["project"]["goals"]:
                compacted["project"]["goals"].pop(0)
                continue
            compacted["session"]["summary"] = self._clip(compacted["session"]["summary"], 120)
            compacted["project"]["summary"] = self._clip(compacted["project"]["summary"], 100)
            compacted["ephemeral"]["last_assistant_message"] = ""
            compacted["ephemeral"]["last_user_message"] = ""
            if len(self._serialize(compacted).encode("utf-8")) <= self.max_bytes:
                break
            compacted["session"]["summary"] = "Session compacted."
            compacted["project"]["summary"] = "Project memory compacted."
            if len(self._serialize(compacted).encode("utf-8")) <= self.max_bytes:
                break
            raise RuntimeError("Unable to compact memory under the 2KB limit.")

        return compacted

    def _trim_list(self, memory: Dict[str, Any], key_path: tuple[str, str]) -> None:
        target = memory[key_path[0]][key_path[1]]
        if target:
            target.pop(0)

    def _clear_list(self, memory: Dict[str, Any], key_path: tuple[str, str]) -> None:
        memory[key_path[0]][key_path[1]] = []

    def _trim_string(self, memory: Dict[str, Any], key_path: tuple[str, str], limit: int) -> None:
        current = memory[key_path[0]][key_path[1]]
        memory[key_path[0]][key_path[1]] = self._clip(current, limit)

    def _normalize_list(self, values: List[str], limit: int, char_limit: int) -> List[str]:
        normalized: List[str] = []
        for value in values:
            if not value:
                continue
            clipped = self._clip(str(value), char_limit)
            if clipped not in normalized:
                normalized.append(clipped)
        return normalized[-limit:]

    def _append_unique(self, values: List[str], item: str, limit: int) -> List[str]:
        normalized = [value for value in values if value != item]
        normalized.append(item)
        return normalized[-limit:]

    def _merge_paths(self, existing: List[str], incoming: List[str], limit: int) -> List[str]:
        merged = list(existing)
        for value in incoming:
            relative = self._relativize(value)
            if not relative:
                continue
            if relative in merged:
                merged.remove(relative)
            merged.append(relative)
        return merged[-limit:]

    def _relativize(self, value: str) -> str:
        try:
            path = Path(value)
            if path.is_absolute():
                return str(path.relative_to(self.project_root))
            return str(path)
        except Exception:
            return str(value)

    def _clip(self, value: Any, limit: int) -> str:
        text = " ".join(str(value).split())
        if len(text) <= limit:
            return text
        return text[: max(limit - 3, 0)].rstrip() + "..."


class SecureMemoryManager(MemoryManager):
    """MemoryManager with At-Rest Encryption using Fernet."""

    def __init__(self, project_root: Path, password: Optional[str] = None, config: Optional[DeepSleepConfig] = None) -> None:
        super().__init__(project_root, config)
        self.cipher = self._init_cipher(password) if password else None

    def _init_cipher(self, password: str) -> Fernet:
        # Derive key from password + project_path (unique per project)
        salt = hashlib.sha256(str(self.project_root).encode()).digest()
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        return Fernet(base64.urlsafe_b64encode(key[:32]))

    def _write_atomic(self, memory: Dict[str, Any]) -> None:
        memory = copy.deepcopy(memory)
        memory["meta"]["updated_at"] = utc_now()
        raw = self._serialize(memory)
        memory["meta"]["byte_size"] = len(raw.encode("utf-8"))
        raw = self._serialize(memory)

        if self.cipher:
            raw = self.cipher.encrypt(raw.encode()).decode()
            logger.debug("memory_encrypt", path=str(self.memory_path))

        tmp_path = self.memory_path.with_suffix('.tmp')
        tmp_path.write_text(raw, encoding="utf-8")
        tmp_path.replace(self.memory_path)

    def _unsafe_load(self) -> Dict[str, Any]:
        if not self.memory_path.exists():
            return self.default_memory()

        raw = self.memory_path.read_text(encoding="utf-8")
        if self.cipher:
            try:
                raw = self.cipher.decrypt(raw.encode()).decode()
            except Exception as exc:
                logger.error("memory_decrypt_failed", error=str(exc))
                raise RuntimeError("Failed to decrypt memory. Wrong password?")
        
        return json.loads(raw)
