import json
from pathlib import Path

from deepsleep_ai.memory_manager import MAX_MEMORY_BYTES, MemoryManager


def test_init_creates_memory_file(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    path = manager.initialize()

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["session"]["summary"] == "No session summary yet."


def test_compactor_keeps_memory_under_2kb(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize()
    memory = manager.load()
    memory["project"]["summary"] = "project " * 200
    memory["session"]["summary"] = "session " * 300
    memory["project"]["goals"] = [f"goal-{index}-" + ("x" * 80) for index in range(10)]
    memory["project"]["facts"] = [f"fact-{index}-" + ("y" * 80) for index in range(10)]
    memory["session"]["recent_tasks"] = [f"task-{index}-" + ("z" * 80) for index in range(10)]
    memory["session"]["recent_files"] = [f"folder/{index}/nested/path/file.py" for index in range(20)]
    memory["ephemeral"]["recent_changes"] = [f"modified:file-{index}.py" for index in range(20)]
    memory["ephemeral"]["open_questions"] = ["why " * 50 for _ in range(8)]

    compacted = manager.save(memory)

    assert manager.memory_path.stat().st_size <= MAX_MEMORY_BYTES
    assert compacted["meta"]["compacted"] is True


def test_record_dream_updates_session(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize()

    manager.record_dream(
        summary="Worked on cli.py and memory_manager.py to improve startup.",
        changed_files=["src/deepsleep_ai/cli.py", "src/deepsleep_ai/memory_manager.py"],
        model_name="deepseek-r1",
    )

    saved = manager.load()
    assert "cli.py" in ",".join(saved["session"]["recent_files"])
    assert saved["session"]["last_dream_at"] is not None
