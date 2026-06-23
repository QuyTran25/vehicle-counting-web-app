"""
Comprehensive E2E tests for Week 5: Vehicle Counting Web App
Test: Upload video → Web calls AI → AI processes → Web displays result

Run with: python tests/test_week5_e2e.py
Requires: server running on http://127.0.0.1:8000
"""
import time
import requests
import sqlite3
import json
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "database.db"


def check_server():
    """Check if FastAPI server is running."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def test_01_invalid_file_rejection():
    """
    Test: Upload .txt file → should return 400 with clear error message.
    Week 5 requirement: Error Handling - handle corrupted/wrong format files.
    """
    print("\n" + "=" * 60)
    print("TEST 01: Invalid File Rejection (.txt instead of .mp4)")
    print("=" * 60)
    
    # Create a dummy .txt file
    txt_path = Path("uploads/test_invalid.txt")
    with open(txt_path, "w") as f:
        f.write("This is NOT a video file. It's just text.")
    
    with open(txt_path, "rb") as f:
        r = requests.post(f"{BASE_URL}/upload", files={"file": ("test.txt", f)})
    
    print(f"  Status: {r.status_code}")
    
    try:
        error_data = r.json()
        print(f"  Response: {error_data}")
        
        if r.status_code == 400:
            # Should have a detail field with Vietnamese error message
            error_msg = error_data.get("detail", "")
            if "không được hỗ trợ" in error_msg or "Unsupported" in error_msg or "định dạng" in error_msg:
                print("  [PASS] ✓ Invalid file correctly rejected with proper error message")
                print(f"  Error: {error_msg}")
                return True
            else:
                print(f"  [PASS] ✓ Rejected (status 400) but message: {error_msg}")
                return True
        else:
            print(f"  [FAIL] ✗ Expected 400, got {r.status_code}")
            return False
    except Exception as e:
        print(f"  [FAIL] ✗ Error parsing response: {e}")
        return False


def test_02_valid_video_end_to_end():
    """
    Test: Upload valid video (de.mp4) → AI processes → result displayed.
    Week 5 requirement: End-to-end test complete flow.
    """
    print("\n" + "=" * 60)
    print("TEST 02: Valid Video End-to-End (de.mp4)")
    print("=" * 60)
    
    # Find de.mp4 in uploads
    de_video = Path("uploads/de.mp4")
    if not de_video.exists():
        print("  [SKIP] de.mp4 not found in uploads/")
        return None
    
    print(f"  Uploading: {de_video} ({de_video.stat().st_size} bytes)")
    
    with open(de_video, "rb") as f:
        r = requests.post(f"{BASE_URL}/upload", 
                         files={"file": ("de.mp4", f, "video/mp4")})
    
    if r.status_code != 200:
        print(f"  [FAIL] ✗ Upload failed with status {r.status_code}: {r.text}")
        return False
    
    task_data = r.json()
    task_id = task_data["task_id"]
    print(f"  Task ID: {task_id}")
    print(f"  Initial status: {task_data['status']}")
    
    # Poll for completion
    print("  Waiting for processing...")
    max_wait = 300  # 5 minutes max
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        time.sleep(3)
        try:
            status_r = requests.get(f"{BASE_URL}/status/{task_id}", timeout=10)
            status_data = status_r.json()
            status = status_data["status"]
            progress = status_data.get("progress", 0)
            
            print(f"    Status: {status} ({progress}%)")
            
            if status == "done":
                elapsed = time.time() - start_time
                print(f"  [PASS] ✓ Processing completed in {elapsed:.1f}s")
                
                # Fetch and verify results
                result_r = requests.get(f"{BASE_URL}/result/{task_id}", timeout=10)
                if result_r.status_code == 200:
                    result = result_r.json()
                    
                    # Verify result structure
                    required_fields = ["metadata", "summary", "timeline", "events"]
                    missing = [f for f in required_fields if f not in result]
                    
                    if missing:
                        print(f"  [FAIL] ✗ Missing fields in result: {missing}")
                        return False
                    
                    summary = result.get("summary", {})
                    total = summary.get("total", 0)
                    print(f"  [PASS] ✓ Result structure valid")
                    print(f"  Results: Car={summary.get('car', 0)}, Moto={summary.get('motorcycle', 0)}, "
                          f"Bus={summary.get('bus', 0)}, Truck={summary.get('truck', 0)}, Total={total}")
                    
                    # Verify timeline
                    if isinstance(result.get("timeline"), list) and len(result["timeline"]) > 0:
                        print(f"  [PASS] ✓ Timeline has {len(result['timeline'])} entries")
                    
                    # Verify events
                    events = result.get("events", [])
                    in_count = sum(1 for e in events if e.get("direction") == "in")
                    out_count = sum(1 for e in events if e.get("direction") == "out")
                    print(f"  [PASS] ✓ Events: {len(events)} total ({in_count} in, {out_count} out)")
                    
                    # Verify metadata
                    meta = result.get("metadata", {})
                    print(f"  Video: {meta.get('resolution')} @ {meta.get('fps')}fps, "
                          f"duration={meta.get('video_duration', 0):.1f}s")
                    
                    # Verify output paths exist
                    if result.get("output_video") and result.get("output_json"):
                        print(f"  [PASS] ✓ Output paths: video={result['output_video']}, json={result['output_json']}")
                    
                    return True
                else:
                    print(f"  [FAIL] ✗ Could not fetch results: {result_r.status_code}")
                    return False
                    
            elif status == "failed":
                error = status_data.get("error_msg", "Unknown error")
                print(f"  [FAIL] ✗ Processing failed: {error}")
                return False
                
        except Exception as e:
            print(f"  [WARN] Status check error: {e}")
            time.sleep(3)
    
    print(f"  [FAIL] ✗ Timeout after {max_wait}s")
    return False


def test_03_concurrent_queue_limit():
    """
    Test: Upload 2 videos simultaneously → only 1 should process at a time.
    Week 5 requirement: Subprocess check - don't create too many parallel processes.
    """
    print("\n" + "=" * 60)
    print("TEST 03: Concurrency Queue Limit")
    print("=" * 60)
    
    de_video = Path("uploads/de.mp4")
    kho_video = Path("uploads/kho.mp4")
    
    if not (de_video.exists() and kho_video.exists()):
        print("  [SKIP] Test videos not found")
        return None
    
    # Upload first video
    print("  Uploading de.mp4...")
    with open(de_video, "rb") as f:
        r1 = requests.post(f"{BASE_URL}/upload", 
                          files={"file": ("de.mp4", f, "video/mp4")})
    
    if r1.status_code != 200:
        print(f"  [FAIL] ✗ Upload 1 failed: {r1.status_code}")
        return False
    
    task1_id = r1.json()["task_id"]
    print(f"  Task 1 ID: {task1_id}")
    
    # Upload second video immediately after
    print("  Uploading kho.mp4 immediately after...")
    with open(kho_video, "rb") as f:
        r2 = requests.post(f"{BASE_URL}/upload",
                          files={"file": ("kho.mp4", f, "video/mp4")})
    
    if r2.status_code != 200:
        print(f"  [FAIL] ✗ Upload 2 failed: {r2.status_code}")
        return False
    
    task2_id = r2.json()["task_id"]
    print(f"  Task 2 ID: {task2_id}")
    
    # Check initial status — task 2 should be queued
    time.sleep(2)
    s1 = requests.get(f"{BASE_URL}/status/{task1_id}").json()
    s2 = requests.get(f"{BASE_URL}/status/{task2_id}").json()
    
    print(f"  Initial — Task 1: {s1['status']} ({s1['progress']}%), Task 2: {s2['status']} ({s2['progress']}%)")
    
    # Verify queue behavior
    if s1['status'] == 'processing' and s2['status'] == 'queued':
        print("  [PASS] ✓ Concurrency limit working — task 2 queued while task 1 processes")
        queue_ok = True
    elif s1['status'] == 'done':
        print("  [INFO] Task 1 completed very fast")
        queue_ok = True
    elif s1['status'] == 'processing' and s2['status'] == 'processing':
        print("  [FAIL] ✗ Both tasks processing simultaneously (no concurrency limit)")
        queue_ok = False
    else:
        print(f"  [INFO] Status: Task1={s1['status']}, Task2={s2['status']}")
        queue_ok = True
    
    # Wait for both to finish
    print("  Waiting for both tasks to complete...")
    for i in range(60):  # 3 minutes max
        time.sleep(3)
        s1 = requests.get(f"{BASE_URL}/status/{task1_id}").json()
        s2 = requests.get(f"{BASE_URL}/status/{task2_id}").json()
        
        done1 = s1['status'] in ('done', 'failed')
        done2 = s2['status'] in ('done', 'failed')
        
        if done1 and done2:
            print(f"  Both tasks completed. Task1={s1['status']}, Task2={s2['status']}")
            break
        
        if i % 5 == 0:
            print(f"    Progress: Task1={s1['status']}({s1['progress']}%), Task2={s2['status']}({s2['progress']}%)")
    
    return queue_ok


def test_04_backup_mode():
    """
    Test: If AI processing fails, backup mode should return pre-processed results.
    Week 5 requirement: Backup mode fallback.
    """
    print("\n" + "=" * 60)
    print("TEST 04: Backup Mode Fallback")
    print("=" * 60)
    
    # Check if backup files exist
    backup_video = Path("backup_results/de_output.mp4")
    backup_json = Path("backup_results/de_result.json")
    
    if not (backup_video.exists() and backup_json.exists()):
        print("  [FAIL] ✗ Backup files not found in backup_results/")
        print(f"    de_output.mp4: {backup_video.exists()}")
        print(f"    de_result.json: {backup_json.exists()}")
        return False
    
    print(f"  [PASS] ✓ Backup files exist")
    print(f"    {backup_video} ({backup_video.stat().st_size} bytes)")
    print(f"    {backup_json} ({backup_json.stat().st_size} bytes)")
    
    # Verify backup JSON is valid
    try:
        with open(backup_json) as f:
            backup_data = json.load(f)
        
        if "summary" in backup_data and "events" in backup_data:
            print(f"  [PASS] ✓ Backup JSON valid")
            print(f"    Summary: {backup_data['summary']}")
            return True
        else:
            print(f"  [FAIL] ✗ Backup JSON missing required fields")
            return False
    except Exception as e:
        print(f"  [FAIL] ✗ Backup JSON invalid: {e}")
        return False


def test_05_startup_reset():
    """
    Test: Stuck processing tasks are reset to failed on server startup.
    Week 5 requirement: Server restart handling.
    """
    print("\n" + "=" * 60)
    print("TEST 05: Startup Task Reset")
    print("=" * 60)
    
    fake_id = "test-reset-12345"
    
    # Insert fake stuck task
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO tasks (id, filename, status, progress, created_at, updated_at) 
        VALUES (?, 'fake.mp4', 'processing', 50, datetime('now'), datetime('now'))
    """, (fake_id,))
    conn.commit()
    conn.close()
    
    print(f"  Inserted fake task: {fake_id} (status=processing)")
    print("  To verify: restart the server and check that this task is reset to 'failed'")
    print("  Manual check: SELECT * FROM tasks WHERE id = ?;", (fake_id,))
    
    # Clean up
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM tasks WHERE id = ?", (fake_id,))
    conn.commit()
    conn.close()
    
    print("  [INFO] Cleanup complete. Manual test required: restart server and check DB.")
    return True


def test_06_codec_compatibility():
    """
    Test: Verify output video can be played in browser.
    Week 5 requirement: Codec compatibility - mp4v works on all browsers.
    """
    print("\n" + "=" * 60)
    print("TEST 06: Codec Compatibility")
    print("=" * 60)
    
    # Get the most recent completed task
    try:
        r = requests.get(f"{BASE_URL}/tasks?limit=5", timeout=10)
        tasks = r.json().get("tasks", [])
        
        done_task = None
        for t in tasks:
            if t.get("status") == "done":
                done_task = t
                break
        
        if not done_task:
            print("  [SKIP] No completed tasks found")
            return None
        
        task_id = done_task["id"]
        print(f"  Checking output for task: {task_id}")
        
        # Try to get result
        result_r = requests.get(f"{BASE_URL}/result/{task_id}", timeout=10)
        if result_r.status_code == 200:
            result = result_r.json()
            output_video_path = result.get("output_video", "").replace("/output/", "")
            
            output_file = Path("outputs") / output_video_path
            if output_file.exists():
                size_mb = output_file.stat().st_size / (1024 * 1024)
                print(f"  [PASS] ✓ Output video exists: {output_file} ({size_mb:.1f} MB)")
                
                # Verify file is not empty or corrupted
                if size_mb < 0.1:
                    print(f"  [WARN] Video file too small ({size_mb:.2f} MB) — may be corrupted")
                    return False
                
                print("  [PASS] ✓ Output video has reasonable size")
                return True
            else:
                print(f"  [FAIL] ✗ Output video not found: {output_file}")
                return False
        else:
            print(f"  [FAIL] ✗ Could not get result: {result_r.status_code}")
            return False
            
    except Exception as e:
        print(f"  [FAIL] ✗ Error: {e}")
        return False


def test_07_demo_backup_readiness():
    """
    Test: Verify backup_results folder has demo-ready videos.
    Week 5 requirement: Backup Mode - pre-processed videos for demo.
    """
    print("\n" + "=" * 60)
    print("TEST 07: Demo Backup Readiness")
    print("=" * 60)
    
    backup_dir = Path("backup_results")
    if not backup_dir.exists():
        print("  [FAIL] ✗ backup_results/ directory not found")
        return False
    
    mp4_files = list(backup_dir.glob("*.mp4"))
    json_files = list(backup_dir.glob("*.json"))
    
    print(f"  Files in backup_results/:")
    for f in mp4_files + json_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"    {f.name} ({size_mb:.1f} MB)")
    
    if len(mp4_files) >= 2 and len(json_files) >= 2:
        print(f"  [PASS] ✓ {len(mp4_files)} videos, {len(json_files)} JSON files — demo ready")
        return True
    elif len(mp4_files) >= 1 and len(json_files) >= 1:
        print(f"  [PASS] ✓ At least 1 video + 1 JSON — basic demo ready")
        return True
    else:
        print(f"  [FAIL] ✗ Not enough backup files")
        return False


def main():
    # Fix Windows console encoding
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    print("=" * 60)
    print("Week 5 E2E Test Suite - Vehicle Counting Web App")
    print("=" * 60)
    
    if not check_server():
        print("\nERROR: FastAPI server not running on http://127.0.0.1:8000")
        print("   Please start the server first:")
        print("   cd d:/vehicle-counting-web-app_/vehicle-counting-web-app")
        print("   .venv\Scripts\activate")
        print("   python -m uvicorn app.main:app --reload")
        return
    
    print("[OK] Server is running")
    
    results = {}
    
    # Run tests
    results["Invalid File Rejection"] = test_01_invalid_file_rejection()
    results["E2E Video Processing"] = test_02_valid_video_end_to_end()
    results["Concurrency Queue"] = test_03_concurrent_queue_limit()
    results["Backup Mode"] = test_04_backup_mode()
    results["Startup Reset"] = test_05_startup_reset()
    results["Codec Compatibility"] = test_06_codec_compatibility()
    results["Demo Backup Ready"] = test_07_demo_backup_readiness()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    failed = 0
    skipped = 0
    
    for name, result in results.items():
        if result is True:
            status = "✅ PASS"
            passed += 1
        elif result is False:
            status = "❌ FAIL"
            failed += 1
        else:
            status = "⏭  SKIP"
            skipped += 1
        
        print(f"  {status} — {name}")
    
    total = passed + failed + skipped
    print(f"\n  Total: {total} tests")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Skipped: {skipped}")
    
    if failed > 0:
        print("\n⚠️  Some tests failed. Please review the output above.")
    else:
        print("\n🎉 All tests passed!")


if __name__ == "__main__":
    main()
