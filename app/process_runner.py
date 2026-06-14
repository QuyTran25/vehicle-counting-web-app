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

# Biểu thức chính quy để tìm phần trăm tiến trình trong log stdout
PROGRESS_PATTERN = re.compile(r"⏳\s*(\d+)%")

def run_process_in_background(task_id: str, video_path: str):
    """
    Chạy background thread để kích hoạt subprocess YOLO và cập nhật tiến độ vào DB.
    """
    thread = threading.Thread(
        target=_process_video_subprocess,
        args=(task_id, video_path),
        daemon=True
    )
    thread.start()

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
                # In ra log console của server (an toàn với mã hóa Windows console)
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
            db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)
            
    except Exception as e:
        error_msg = f"Runner error: {str(e)}"
        print(f"[ProcessRunner] Task {task_id} exception: {error_msg}")
        db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)
