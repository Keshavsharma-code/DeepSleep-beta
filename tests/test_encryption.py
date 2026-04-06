import pytest
from pathlib import Path
from deepsleep_ai.memory_manager import SecureMemoryManager, ENC_MAGIC
import base64

def test_aes256_encryption_decryption(tmp_path: Path) -> None:
    # Setup
    project_root = tmp_path
    password = "super-secret-password"
    manager = SecureMemoryManager(project_root, password=password)
    
    # Save some secret data
    secret_data = manager.default_memory()
    secret_data["project"]["summary"] = "Classified Project X"
    manager.save(secret_data)
    
    # Verify file is physically encrypted and contains magic
    raw_content = (project_root / ".deepsleep" / "memory.json").read_text()
    decoded = base64.b64decode(raw_content)
    assert decoded.startswith(ENC_MAGIC.encode())
    assert "Classified Project X" not in raw_content
    
    # Load with correct password
    new_manager = SecureMemoryManager(project_root, password=password)
    loaded_data = new_manager.load()
    assert loaded_data["project"]["summary"] == "Classified Project X"

def test_aes256_wrong_password_fails(tmp_path: Path) -> None:
    project_root = tmp_path
    password = "correct-password"
    manager = SecureMemoryManager(project_root, password=password)
    manager.initialize()
    
    # Try to load with wrong password
    bad_manager = SecureMemoryManager(project_root, password="wrong-password")
    with pytest.raises(RuntimeError, match="Invalid password"):
        bad_manager.load()

def test_encryption_salt_is_unique(tmp_path: Path) -> None:
    project_root = tmp_path
    password = "password"
    
    manager = SecureMemoryManager(project_root, password=password)
    manager.initialize(force=True)
    content1 = (project_root / ".deepsleep" / "memory.json").read_text()
    
    # Re-save (should generate new salt/nonce)
    manager.save(manager.load())
    content2 = (project_root / ".deepsleep" / "memory.json").read_text()
    
    assert content1 != content2 # Different salt or nonce every time
