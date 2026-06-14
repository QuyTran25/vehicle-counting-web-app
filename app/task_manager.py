"""
task_manager.py - Quản lý kiểm tra trạng thái video
"""
from pathlib import Path
from app.database import Database
from app.config import OUTPUTS_DIR

def is_task_completed(task_id: str) -> bool:
    """
    Kiểm tra trạng thái từ DB hoặc kiểm tra sự tồn tại của file kết quả JSON.
    """
    db = Database()
    task = db.get_task(task_id)
    if task and task.get("status") == "done":
        return True
    
    # Fallback: kiểm tra sự tồn tại của file JSON kết quả
    json_path = OUTPUTS_DIR / f"{task_id}_result.json"
    return json_path.exists()
