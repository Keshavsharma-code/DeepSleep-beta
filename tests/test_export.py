from __future__ import annotations
import json
import pytest
from pathlib import Path
from deepsleep_ai.memory_manager import MemoryManager
from deepsleep_ai.cli import _render_markdown_report


@pytest.fixture
def memory_manager(tmp_path: Path) -> MemoryManager:
    manager = MemoryManager(tmp_path)
    manager.initialize(force=True)
    return manager


def test_export_empty(memory_manager: MemoryManager) -> None:
    assert memory_manager.export_activity() == []


def test_export_all_entries(memory_manager: MemoryManager) -> None:
    activity_path = memory_manager.activity_log_path
    with activity_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2025-01-01T10:00:00+00:00", "type": "dream", "payload": {"summary": "test"}}))
        f.write("\n")
        f.write(json.dumps({"timestamp": "2025-01-01T10:05:00+00:00", "type": "chat_turn", "payload": {"user": "hi", "assistant": "hi"}}))
        f.write("\n")
        f.write(json.dumps({"timestamp": "2025-01-01T10:10:00+00:00", "type": "file_event", "payload": {"path": "a.py", "event_type": "modified"}}))

    entries = memory_manager.export_activity()
    assert len(entries) == 3
    assert entries[0]["type"] == "dream"
    assert entries[1]["type"] == "chat_turn"
    assert entries[2]["type"] == "file_event"


def test_export_since_filter(memory_manager: MemoryManager) -> None:
    activity_path = memory_manager.activity_log_path
    with activity_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2024-12-01T10:00:00+00:00", "type": "dream", "payload": {"summary": "old"}}))
        f.write("\n")
        f.write(json.dumps({"timestamp": "2025-01-01T10:00:00+00:00", "type": "dream", "payload": {"summary": "new"}}))
        f.write("\n")

    entries = memory_manager.export_activity(since="2025-01-01")
    assert len(entries) == 1
    assert entries[0]["payload"]["summary"] == "new"


def test_export_since_filters_all(memory_manager: MemoryManager) -> None:
    activity_path = memory_manager.activity_log_path
    with activity_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2025-01-01T10:00:00+00:00", "type": "dream", "payload": {"summary": "test"}}))
        f.write("\n")

    entries = memory_manager.export_activity(since="2099-01-01")
    assert entries == []


def test_export_malformed_line(memory_manager: MemoryManager) -> None:
    activity_path = memory_manager.activity_log_path
    with activity_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2025-01-01T10:00:00+00:00", "type": "dream", "payload": {"summary": "valid"}}))
        f.write("\n")
        f.write("not valid json\n")
        f.write(json.dumps({"timestamp": "2025-01-01T10:05:00+00:00", "type": "chat_turn", "payload": {"user": "hi"}}))
        f.write("\n")

    entries = memory_manager.export_activity()
    assert len(entries) == 2
    assert entries[0]["type"] == "dream"
    assert entries[1]["type"] == "chat_turn"


def test_render_markdown_contains_sections() -> None:
    entries = [
        {"timestamp": "2025-04-07T09:12:00+00:00", "type": "dream", "payload": {"summary": "Refactored auth"}},
        {"timestamp": "2025-04-07T10:04:00+00:00", "type": "chat_turn", "payload": {"user": "What was I working on?"}},
        {"timestamp": "2025-04-07T11:00:00+00:00", "type": "file_event", "payload": {"path": "src/auth.py", "event_type": "modified"}},
    ]
    output = _render_markdown_report(entries, "test-project")
    assert "## 🌙 Dream Summaries" in output
    assert "## 💬 Chat Activity" in output
    assert "## 📂 Files Touched" in output
    assert "Refactored auth" in output
    assert "What was I working on?" in output


def test_render_markdown_empty_entries() -> None:
    output = _render_markdown_report([], "test-project")
    assert "_No activity recorded._" in output