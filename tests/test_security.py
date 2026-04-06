import os
from pathlib import Path
from deepsleep_ai.cli import _resolve_safely, _is_sensitive, _collect_file_context
from deepsleep_ai.memory_manager import MemoryManager

def test_path_traversal_blocked(tmp_path: Path) -> None:
    # Create file outside project
    project_root = tmp_path / "project"
    project_root.mkdir()
    
    outside = tmp_path / "secret.txt"
    outside.write_text("leak")
    
    # Try to access via traversal
    resolved = _resolve_safely(project_root, "../secret.txt")
    assert resolved is None

def test_sensitive_files_blocked(tmp_path: Path) -> None:
    project_root = tmp_path
    env_file = project_root / ".env"
    env_file.write_text("API_KEY=123")
    
    assert _is_sensitive(env_file) is True
    
    resolved = _resolve_safely(project_root, ".env")
    assert resolved is None

def test_collect_file_context_sanitization(tmp_path: Path) -> None:
    project_root = tmp_path
    manager = MemoryManager(project_root)
    manager.initialize()
    
    # Create a legitimate file
    legit = project_root / "app.py"
    legit.write_text("print('hello')")
    
    # Create a sensitive file
    secret = project_root / "secrets.json"
    secret.write_text('{"key": "val"}')
    
    context = _collect_file_context(project_root, "Check app.py and secrets.json", manager)
    assert "app.py" in context
    assert "secrets.json" not in context
