from pathlib import Path

from deepsleep_ai.llm_client import LLMReply
from deepsleep_ai.memory_manager import MemoryManager
from deepsleep_ai.watcher import DreamWatcher


class FakeClient:
    model = "fake-local-model"

    def summarize_activity(self, changed_files, file_snippets, previous_summary):
        return LLMReply(
            text=f"Dreamed about {', '.join(changed_files)} after {previous_summary}",
            model=self.model,
            used_fallback=True,
        )


def test_watcher_records_change_and_dreams(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize()

    target = tmp_path / "app.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    watcher = DreamWatcher(
        project_root=tmp_path,
        memory_manager=manager,
        llm_client=FakeClient(),
        idle_seconds=300,
    )
    assert watcher.record_change(str(target), "modified") is True
    reply = watcher.dream_once_if_idle(force=True)

    assert reply is not None
    assert "app.py" in reply.text
    saved = manager.load()
    assert saved["session"]["last_dream_at"] is not None
    assert "app.py" in ",".join(saved["session"]["recent_files"])


def test_watcher_force_snapshot_can_dream_without_pending_events(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize()

    target = tmp_path / "notes.py"
    target.write_text("value = 1\n", encoding="utf-8")

    watcher = DreamWatcher(
        project_root=tmp_path,
        memory_manager=manager,
        llm_client=FakeClient(),
        idle_seconds=300,
        snapshot_window_seconds=3600,
    )
    reply = watcher.dream_once_if_idle(force=True)

    assert reply is not None
    assert "notes.py" in reply.text
