from __future__ import annotations
import pytest
from pathlib import Path
from deepsleep_ai.memory_manager import MemoryManager


@pytest.fixture
def memory_manager(tmp_path: Path) -> MemoryManager:
    manager = MemoryManager(tmp_path)
    manager.initialize(force=True)
    return manager


def test_forget_session_layer(memory_manager: MemoryManager) -> None:
    memory_manager.record_project_note("Important project fact")
    memory_manager.record_chat_turn("test user", "test assistant", ["test.py"])
    memory_manager.forget_layer("session")
    memory = memory_manager.load()
    defaults = memory_manager.default_memory()
    assert memory["session"] == defaults["session"]
    assert memory["project"]["facts"] != defaults["project"]["facts"]


def test_forget_ephemeral_layer(memory_manager: MemoryManager) -> None:
    memory_manager.record_project_note("Important project fact")
    memory_manager.record_chat_turn("test user", "test assistant", ["test.py"])
    memory_manager.forget_layer("ephemeral")
    memory = memory_manager.load()
    defaults = memory_manager.default_memory()
    assert memory["ephemeral"] == defaults["ephemeral"]
    assert memory["session"]["recent_files"] != defaults["session"]["recent_files"]
    assert memory["project"]["facts"] != defaults["project"]["facts"]


def test_forget_project_layer(memory_manager: MemoryManager) -> None:
    memory_manager.record_project_note("Some important fact")
    memory_manager.forget_layer("project")
    memory = memory_manager.load()
    defaults = memory_manager.default_memory()
    assert memory["project"] == defaults["project"]


def test_forget_invalid_layer(memory_manager: MemoryManager) -> None:
    with pytest.raises(ValueError, match="Layer must be one of"):
        memory_manager.forget_layer("invalid")


def test_forget_key_valid(memory_manager: MemoryManager) -> None:
    memory_manager.record_chat_turn("task one", "answer one", ["a.py", "b.py"])
    memory_manager.forget_key("session", "recent_files")
    memory = memory_manager.load()
    defaults = memory_manager.default_memory()
    assert memory["session"]["recent_files"] == defaults["session"]["recent_files"]


def test_forget_key_invalid(memory_manager: MemoryManager) -> None:
    with pytest.raises(ValueError, match="not found"):
        memory_manager.forget_key("session", "nonexistent_key")


def test_forget_key_wrong_layer(memory_manager: MemoryManager) -> None:
    with pytest.raises(ValueError, match="not found"):
        memory_manager.forget_key("nonexistent", "summary")