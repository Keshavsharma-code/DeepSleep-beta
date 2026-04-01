from pathlib import Path

from typer.testing import CliRunner

from deepsleep_ai.cli import app


def test_doctor_reports_local_setup_when_ollama_is_offline(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["doctor", str(tmp_path), "--host", "http://127.0.0.1:9"],
    )

    assert result.exit_code == 0
    assert "OK   memory-file" in result.stdout
    assert "WARN ollama-host" in result.stdout
