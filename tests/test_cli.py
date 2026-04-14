import subprocess
import sys
from pathlib import Path

from deepsleep_ai.memory_manager import MemoryManager


def test_chat_exits_cleanly_on_quit(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize()

    result = subprocess.run(
        [sys.executable, "-m", "deepsleep_ai.cli", "--path", str(tmp_path)],
        input="What was I doing?\n/quit\n",
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0 and "NoConsoleScreenBufferError" in result.stderr:
        import pytest
        pytest.skip("No Windows console available in this environment")

    assert result.returncode == 0
    assert "DeepSleep ended." in result.stdout
