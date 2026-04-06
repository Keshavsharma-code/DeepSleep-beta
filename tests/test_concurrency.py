import multiprocessing
import time
from pathlib import Path
from deepsleep_ai.memory_manager import MemoryManager

def writer(tmp_path, index):
    manager = MemoryManager(tmp_path)
    for i in range(20):
        manager.record_chat_turn(f"msg-{index}-{i}", "resp", ["file.py"])
        time.sleep(0.01)

def test_concurrent_access_handled_gracefully(tmp_path: Path) -> None:
    # Initialize first
    manager = MemoryManager(tmp_path)
    manager.initialize()
    
    # Run 4 processes simultaneously
    procs = [multiprocessing.Process(target=writer, args=(tmp_path, i)) for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    
    # Verify no corruption and all turns were recorded (or at least it didn't crash)
    memory = manager.load()
    assert memory["version"] == 1
    # Since we have a 5-turn limit in recent_tasks in memory_manager.py, 
    # we can't easily check the count without looking at the activity log.
    assert manager.activity_log_path.exists()
    with open(manager.activity_log_path, "r") as f:
        lines = f.readlines()
        # Each process did 20 turns, so 4 * 20 = 80 lines expected.
        assert len(lines) >= 80
