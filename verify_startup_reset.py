import sqlite3
import time
import requests
import subprocess
import sys
from pathlib import Path

DB_PATH = "database.db"
BASE_URL = "http://127.0.0.1:8000"

def main():
    print("--- Automated Startup Reset Test ---")
    
    # 1. Insert fake task in DB
    fake_id = "automated-reset-task-999"
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO tasks (id, filename, status, progress, created_at, updated_at) VALUES (?, 'fake_startup.mp4', 'processing', 33, datetime('now'), datetime('now'))",
        (fake_id,)
    )
    conn.commit()
    conn.close()
    print(f"Inserted task {fake_id} with status 'processing'")

    # 2. Check current status in DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (fake_id,)).fetchone()
    conn.close()
    print(f"Verified initial status in DB: {dict(row)['status']}")

    # Note: We will kill the running server and start it again manually via this script or run command.
    # But wait, we can just run the cleanup code directly to verify it works, or simulate the startup event!
    # Let's import get_connection and startup_event from app.main to test it directly in this process!
    sys.path.insert(0, str(Path(__file__).parent))
    from app.main import startup_event
    
    # Run the startup event function directly
    print("Running startup_event() directly...")
    import asyncio
    asyncio.run(startup_event())
    
    # Verify status in DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (fake_id,)).fetchone()
    conn.close()
    
    task = dict(row)
    print(f"Status after startup_event: {task['status']}")
    print(f"Error Message: {task['error_msg']}")
    if task['status'] == 'failed' and 'Server restarted' in task['error_msg']:
        print("[SUCCESS] Automated startup reset verified successfully!")
    else:
        print("[FAIL] Startup reset failed.")

if __name__ == "__main__":
    main()
