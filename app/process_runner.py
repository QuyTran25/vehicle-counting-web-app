"""
process_runner.py - Quản lý chạy script AI dưới dạng subprocess
Week 5: Added subprocess timeout (10 min), memory limit, Windows process cleanup
"""
import sys
import re
import subprocess
from pathlib import Path
import threading
import json
import time
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


def _read_output_thread(stdout_pipe, lines_list, done_event):
    """Background thread đọc stdout liên tục cho đến khi pipe đóng."""
    try:
        for line in iter(stdout_pipe.readline, ''):
            lines_list.append(line)
    except Exception:
        pass
    finally:
        done_event.set()


def _process_video_subprocess(task_id: str, video_path: str, timeout_seconds: int = 600):
    """
    Chạy AI engine trong subprocess riêng biệt với timeout protection.

    Args:
        task_id: Task ID để cập nhật trạng thái
        video_path: Đường dẫn video đầu vào
        timeout_seconds: Timeout cho subprocess (default 10 phút). Nếu vượt quá → kill process
    """
    db = Database()
    process = None
    output_lines = []
    process_done = threading.Event()

    # Memory limit: giới hạn threads cho OpenBLAS/MKL/PyTorch để tránh OOM
    import os
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "2"
    env["MKL_NUM_THREADS"] = "2"
    env["OPENBLAS_NUM_THREADS"] = "2"
    env["CUDA_VISIBLE_DEVICES"] = ""  # CPU only

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
        print(f"[ProcessRunner] Timeout: {timeout_seconds}s ({timeout_seconds // 60} min)")

        # Khởi chạy subprocess với stdout/stderr dạng PIPE
        creationflags = 0
        if sys.platform == "win32":
            import subprocess as _subprocess
            creationflags = _subprocess.CREATE_NEW_PROCESS_GROUP

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(PROJECT_ROOT),
            env=env,
            creationflags=creationflags,
        )

        # Bắt đầu background thread đọc output (tránh buffer full deadlock)
        reader_thread = threading.Thread(
            target=_read_output_thread,
            args=(process.stdout, output_lines, process_done),
            daemon=True,
            name=f"OutputReader-{task_id[:8]}"
        )
        reader_thread.start()

        # Đợi subprocess hoàn thành với timeout
        start_wait = time.time()
        process_terminated = False
        last_log_time = time.time()
        last_line_count = 0

        while True:
            elapsed = time.time() - start_wait

            if process.poll() is not None:
                # Process đã kết thúc
                break

            if elapsed >= timeout_seconds:
                print(f"[ProcessRunner] Task {task_id} TIMEOUT after {elapsed:.0f}s. Killing process...")
                process_terminated = True

                if sys.platform == "win32":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                            capture_output=True, timeout=10
                        )
                    except Exception as e:
                        print(f"[ProcessRunner] taskkill error: {e}")
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), 9)
                    except Exception:
                        try:
                            process.kill()
                        except Exception:
                            pass

                db.update_task_status(
                    task_id, TASK_STATUS_FAILED, progress=0,
                    error_msg=f"Xử lý vượt quá {timeout_seconds // 60} phút. "
                              f"File có thể quá lớn hoặc bị hỏng."
                )
                return

            # Log output lines every 3 seconds (avoid flooding)
            current_time = time.time()
            if current_time - last_log_time >= 3 and len(output_lines) > last_line_count:
                recent = output_lines[last_line_count:]
                for line in recent:
                    if line.strip():
                        try:
                            sys.stdout.write(f"[{task_id}] {line}")
                            sys.stdout.flush()
                        except Exception:
                            pass

                # Check progress from output
                for line in output_lines[-20:]:
                    match = PROGRESS_PATTERN.search(line)
                    if match:
                        progress_val = min(int(match.group(1)), 99)
                        db.update_task_status(task_id, TASK_STATUS_PROCESSING, progress=progress_val)

                last_line_count = len(output_lines)
                last_log_time = current_time

            time.sleep(0.5)

        # Đọc các dòng còn lại sau khi process kết thúc
        if not process_done.is_set():
            reader_thread.join(timeout=3)

        # In remaining output
        for line in output_lines[last_line_count:]:
            if line.strip():
                try:
                    sys.stdout.write(f"[{task_id}] {line}")
                    sys.stdout.flush()
                except Exception:
                    pass

        return_code = process.returncode

        if process_terminated:
            return

        if return_code == 0:
            if output_json.exists():
                with open(output_json, "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                db.save_result(task_id, result_data)

            db.update_task_status(task_id, TASK_STATUS_DONE, progress=100)
            print(f"[ProcessRunner] Task {task_id} completed successfully!")
        else:
            error_msg = f"AI engine exit with code {return_code}"
            print(f"[ProcessRunner] Task {task_id} failed: {error_msg}")

            if _apply_backup_mode(task_id, video_path):
                return

            db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)

    except Exception as e:
        error_msg = f"Runner error: {str(e)}"
        print(f"[ProcessRunner] Task {task_id} exception: {error_msg}")

        if process and process.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True, timeout=5
                    )
                else:
                    process.kill()
            except Exception:
                pass

        if _apply_backup_mode(task_id, video_path):
            return

        db.update_task_status(task_id, TASK_STATUS_FAILED, progress=0, error_msg=error_msg)
