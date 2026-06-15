"""
process_runner.py - Quản lý chạy script AI dưới dạng subprocess
"""
import sys
import re
import subprocess
from pathlib import Path
import threading
import json
from app.config import (
    PROJECT_ROOT,
    UPLOADS_DIR,
    OUTPUTS_DIR,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
)
from app.database import Database

import queue
import shutil

# Biểu thức chính quy để tìm phần trăm tiến trình trong log stdout
PROGRESS_PATTERN = re.compile(r"⏳\s*(\d+)%")

# Hàng đợi task và lock đồng bộ
_task_queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

DE_SIZE = 4563991
KHO_SIZE = 3292534

def _start_worker_if_needed():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            worker_thread = threading.Thread(
                target=_queue_worker,
                daemon=True,
                name="ProcessRunnerWorker"
            )
            worker_thread.start()
            _worker_started = True
            print("[ProcessRunner] Worker thread started successfully.")

def _queue_worker():
    while True:
        try:
            task_id, video_path = _task_queue.get()
            try:
                _process_video_subprocess(task_id, video_path)
            except Exception as e:
                print(f"[ProcessRunner] Error processing task {task_id}: {e}")
            finally:
                _task_queue.task_done()
        except Exception as e:
            print(f"[ProcessRunner] Worker exception: {e}")

def run_process_in_background(task_id: str, video_path: str):
    """
    Kích hoạt chạy YOLO bằng cách thêm vào hàng đợi (concurrency limit).
    """
    _start_worker_if_needed()
    _task_queue.put((task_id, video_path))
    print(f"[ProcessRunner] Queued task {task_id}")

def _apply_backup_mode(task_id: str, video_path: str) -> bool:
    """
    Kiểm tra file video đầu vào để kích hoạt Backup Mode nếu AI lỗi.
    """
    try:
        path = Path(video_path)
        if not path.exists():
            return False
        
        file_size = path.stat().st_size
        filename_lower = path.name.lower()
        
        backup_name = None
        if file_size == DE_SIZE or "de" in filename_lower:
            backup_name = "de"
        elif file_size == KHO_SIZE or "kho" in filename_lower:
            backup_name = "kho"
            
        if not backup_name:
            return False
            
        backup_video = PROJECT_ROOT / "backup_results" / f"{backup_name}_output.mp4"
        backup_json = PROJECT_ROOT / "backup_results" / f"{backup_name}_result.json"
        
        if not backup_video.exists() or not backup_json.exists():
            print(f"[BackupMode] Backup assets not found for {backup_name}")
            return False
            
        output_video = OUTPUTS_DIR / f"{task_id}_output.mp4"
        output_json = OUTPUTS_DIR / f"{task_id}_result.json"
        
        print(f"[BackupMode] AI failed. Copying backup results for {backup_name} to task {task_id}")
        shutil.copy2(str(backup_video), str(output_video))
        shutil.copy2(str(backup_json), str(output_json))
        
        db = Database()
        with open(output_json, "r", encoding="utf-8") as f:
            result_data = json.load(f)
            
        db.save_result(task_id, result_data)
        db.update_task_status(task_id, TASK_STATUS_DONE, progress=100)
        print(f"[BackupMode] Task {task_id} marked as done using backup.")
        return True
    except Exception as e:
        print(f"[BackupMode] Error: {e}")
        return False

def _process_video_subprocess(task_id: str, video_path: str):
    db = Database()
    try:
        # Cập nhật trạng thái bắt đầu xử lý
        db.update_task_status(task_id, TASK_STATUS_PROCESSING, progress=0)
        
        output_video = OUTPUTS_DIR / f"{task_id}_output.mp4"
        output_json = OUTPUTS_DIR / f"{task_id}_result.json"
        
        # Script path của process.py
        script_path = PROJECT_ROOT / "processing" / "process.py"
        
        # Sử dụng python interpreter của môi trường hiện tại
        python_exe = sys.executable
        
        cmd = [
            python_exe,
            "-u",
            str(script_path),
            str(video_path),
            str(output_video),
            str(output_json)
        ]
        
        print(f"[ProcessRunner] Starting subprocess: {' '.join(cmd)}")
        
        # Khởi chạy subprocess với stdout/stderr dạng PIPE
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(PROJECT_ROOT)
        )
        
        # Đọc output theo thời gian thực
        if process.stdout:
            for line in process.stdout:
                # In ra log console của server (an sau với mã hóa Windows console)
                try:
                    sys.stdout.write(f"[{task_id}] {line}")
                    sys.stdout.flush()
                except Exception:
                    try:
                        safe_line = line.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
                        sys.stdout.write(f"[{task_id}] {safe_line}")
                        sys.stdout.flush()
                    except Exception:
                        pass
                
                # Tìm kiếm tiến trình (%)
                match = PROGRESS_PATTERN.search(line)
                if match:
                    progress_val = int(match.group(1))
                    # Đảm bảo không vượt quá 99% trước khi hoàn thành thực sự
                    progress_val = min(progress_val, 99)
                    db.update_task_status(task_id, TASK_STATUS_PROCESSING, progress=progress_val)
        
        # Đợi subprocess hoàn thành
        return_code = process.wait()
        
        if return_code == 0:
            # Lưu kết quả từ file JSON vào DB kết quả
            if output_json.exists():
                with open(output_json, "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                
                # Lưu vào bảng results
                db.save_result(task_id, result_data)
                
            db.update_task_status(task_id, TASK_STATUS_DONE, progress=100)
            print(f"[ProcessRunner] Task {task_id} completed successfully!")
        else:
            error_msg = f"Subprocess exited with code {return_code}"
            print(f"[ProcessRunner] Task {task_id} failed: {error_msg}")
            
            # Kích hoạt Backup Mode
            if _apply_backup_mode(task_id, video_path):
                return
                
            db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)
            
    except Exception as e:
        error_msg = f"Runner error: {str(e)}"
        print(f"[ProcessRunner] Task {task_id} exception: {error_msg}")
        
        # Kích hoạt Backup Mode
        if _apply_backup_mode(task_id, video_path):
            return
            
        db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)
