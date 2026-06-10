#!/usr/bin/env python3
"""
Script kiểm tra codec của video output.
Đảm bảo video output mở được trên VLC, Chrome, Firefox.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from processing.utils import verify_codec

def main():
    """Kiểm tra codec của tất cả file output trong outputs/"""
    
    outputs_dir = Path("outputs")
    video_files = list(outputs_dir.glob("*_output.mp4"))
    
    if not video_files:
        print("⚠️  Không tìm thấy file video output trong outputs/")
        return
    
    print("=" * 60)
    print("Codec Verification Test")
    print("=" * 60)
    
    results = []
    for video_file in sorted(video_files):
        print(f"\n[VIDEO] Testing: {video_file.name}")
        is_playable, error_msg = verify_codec(str(video_file))
        
        status_icon = "[PASS]" if is_playable else "[FAIL]"
        print(f"   {status_icon} Playable: {is_playable}")
        if error_msg:
            print(f"   [INFO] Message: {error_msg}")
        
        results.append({
            "file": video_file.name,
            "playable": is_playable,
            "message": error_msg or "OK"
        })
    
    # Summary
    print("\n" + "=" * 60)
    print("CODEC CHECK SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results if r["playable"])
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    for result in results:
        status = "[PASS]" if result["playable"] else "[FAIL]"
        print(f"  {status} -- {result['file']}")
        if result["message"] != "OK":
            print(f"       {result['message']}")
    
    print("\nAll files are playable on VLC, Chrome, Firefox!" if passed == total else "\nWarning: Some files may have compatibility issues")

if __name__ == "__main__":
    main()
