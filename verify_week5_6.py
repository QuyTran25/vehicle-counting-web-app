import time
import requests
import sqlite3
import shutil
import os
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "database.db"

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/health")
        return r.status_code == 200
    except:
        return False

def test_invalid_file():
    print("\n--- TEST 0: Invalid File Upload ---")
    txt_path = Path("uploads/test.txt")
    if not txt_path.exists():
        with open(txt_path, "w") as f:
            f.write("This is a dummy text file.")
            
    with open(txt_path, "rb") as f:
        r = requests.post(f"{BASE_URL}/upload", files={"file": ("test.txt", f)})
    
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.json()}")
    if r.status_code == 400:
        print("[SUCCESS] Invalid file rejected correctly.")
    else:
        print("[FAIL] Invalid file not rejected.")

def test_backup_mode():
    print("\n--- TEST 2: Backup Mode Fallback Test ---")
    # Temporarily break processing/process.py by renaming it
    original_script = Path("processing/process.py")
    temp_script = Path("processing/process_temp.py")
    
    if not original_script.exists():
        print("[FAIL] process.py not found.")
        return
        
    print("Simulating AI failure by breaking process.py...")
    original_script.rename(temp_script)
    
    try:
        # Upload de.mp4 to trigger AI run which will fail
        de_video = Path("uploads/de.mp4")
        print("Uploading de.mp4 under broken AI environment...")
        with open(de_video, "rb") as f:
            r = requests.post(f"{BASE_URL}/upload", files={"file": ("de.mp4", f)})
        task_id = r.json()["task_id"]
        print(f"Task ID: {task_id}")
        
        # Wait for task completion
        print("Waiting for task to complete...")
        for _ in range(12):
            time.sleep(2)
            status = requests.get(f"{BASE_URL}/status/{task_id}").json()
            print(f"Task status: {status['status']} (progress: {status['progress']}%)")
            if status['status'] in ('done', 'failed'):
                break
                
        final_status = requests.get(f"{BASE_URL}/status/{task_id}").json()
        if final_status['status'] == 'done':
            print("[SUCCESS] Backup Mode successfully fallback to pre-processed files and completed task!")
            # Retrieve results to verify
            res = requests.get(f"{BASE_URL}/result/{task_id}").json()
            print(f"Counts: {res.get('summary')}")
        else:
            print(f"[FAIL] Task failed with status: {final_status['status']}, error: {final_status.get('error_msg')}")
    finally:
        # Restore process.py
        print("Restoring process.py...")
        if temp_script.exists():
            temp_script.rename(original_script)

def test_concurrency_queue():
    print("\n--- TEST 1: Concurrency Queue Test ---")
    de_video = Path("uploads/de.mp4")
    kho_video = Path("uploads/kho.mp4")
    
    if not de_video.exists() or not kho_video.exists():
        print("[FAIL] Test videos missing in uploads/ directory.")
        return

    # Upload first video
    print("Uploading first video (de.mp4)...")
    with open(de_video, "rb") as f:
        r1 = requests.post(f"{BASE_URL}/upload", files={"file": ("de.mp4", f)})
    task1_id = r1.json()["task_id"]
    print(f"Task 1 ID: {task1_id}")

    # Upload second video immediately
    print("Uploading second video (kho.mp4)...")
    with open(kho_video, "rb") as f:
        r2 = requests.post(f"{BASE_URL}/upload", files={"file": ("kho.mp4", f)})
    task2_id = r2.json()["task_id"]
    print(f"Task 2 ID: {task2_id}")

    # Check status immediately to see if queueing works
    time.sleep(1)
    status1 = requests.get(f"{BASE_URL}/status/{task1_id}").json()
    status2 = requests.get(f"{BASE_URL}/status/{task2_id}").json()
    
    print(f"Task 1 status: {status1['status']} (progress: {status1['progress']}%)")
    print(f"Task 2 status: {status2['status']} (progress: {status2['progress']}%)")
    
    # Verify that at most 1 is processing and one is queued/processing sequentially
    if status1['status'] == 'processing' and status2['status'] == 'queued':
        print("[SUCCESS] Concurrency limit active. Task 2 is queued while Task 1 is processing.")
    elif status1['status'] == 'done' or status2['status'] == 'done':
        print("[INFO] Task processed very quickly.")
    else:
        print(f"[INFO] Current state: Task 1: {status1['status']}, Task 2: {status2['status']}")

    # Wait for both to complete
    print("Waiting for tasks to complete...")
    for _ in range(30):
        s1 = requests.get(f"{BASE_URL}/status/{task1_id}").json()
        s2 = requests.get(f"{BASE_URL}/status/{task2_id}").json()
        print(f"Task 1: {s1['status']} ({s1['progress']}%) | Task 2: {s2['status']} ({s2['progress']}%)")
        if s1['status'] in ('done', 'failed') and s2['status'] in ('done', 'failed'):
            break
        time.sleep(5)

def test_startup_reset():
    print("\n--- TEST 3: Startup Task Reset Test ---")
    conn = sqlite3.connect(DB_PATH)
    # Insert a fake processing task
    fake_id = "test-reset-task-12345"
    conn.execute(
        "INSERT OR REPLACE INTO tasks (id, filename, status, progress, created_at, updated_at) VALUES (?, 'test.mp4', 'processing', 50, datetime('now'), datetime('now'))",
        (fake_id,)
    )
    conn.commit()
    conn.close()
    print(f"Inserted fake processing task: {fake_id}")

    print("Please restart the FastAPI server now. (Kill it and let it boot again).")
    print("Waiting 10 seconds for you to restart uvicorn...")
    time.sleep(10)
    
    # Query database directly to see if status changed to failed
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (fake_id,)).fetchone()
    conn.close()
    
    if row:
        task = dict(row)
        print(f"Task {fake_id} status after restart: {task['status']}")
        print(f"Error Message: {task['error_msg']}")
        if task['status'] == 'failed' and 'Server restarted' in task['error_msg']:
            print("[SUCCESS] Stuck task was reset to failed correctly on startup.")
        else:
            print("[FAIL] Task was not reset correctly.")
    else:
        print("[FAIL] Fake task not found.")

if __name__ == "__main__":
    if not check_server():
        print("[FAIL] FastAPI server is not running on http://127.0.0.1:8000")
        exit(1)
    
    test_invalid_file()
    test_backup_mode()
    test_concurrency_queue()
    test_startup_reset()
