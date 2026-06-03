"""
Test script: Run vehicle detection + tracking on test1lan.mp4 and test2lan.mp4
"""
import sys
import json
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import UPLOADS_DIR, OUTPUTS_DIR
from processing.process import process_video_file


def run_test(video_filename: str):
    """Process a single test video and print results."""
    input_path = UPLOADS_DIR / video_filename
    stem = Path(video_filename).stem
    output_video = OUTPUTS_DIR / f"{stem}_output.mp4"
    output_json = OUTPUTS_DIR / f"{stem}_result.json"

    if not input_path.exists():
        print(f"❌ File not found: {input_path}")
        return None

    print(f"\n{'='*60}")
    print(f"🎬 Processing: {video_filename}")
    print(f"   Input:  {input_path}")
    print(f"   Output: {output_video}")
    print(f"   JSON:   {output_json}")
    print(f"{'='*60}")

    start = time.time()

    def progress_cb(frame_num, total, pct):
        if frame_num % 100 == 0:
            print(f"   ⏳ Frame {frame_num}/{total} ({pct}%)")

    try:
        results = process_video_file(
            str(input_path),
            str(output_video),
            str(output_json),
            callback=progress_cb,
        )
        elapsed = time.time() - start

        print(f"\n✅ Done in {elapsed:.1f}s")
        print(f"\n📊 Summary (unique vehicles):")
        summary = results["summary"]
        print(f"   🚗 Car:        {summary['car']}")
        print(f"   🏍  Motorcycle: {summary['motorcycle']}")
        print(f"   🚌 Bus:        {summary['bus']}")
        print(f"   🚚 Truck:      {summary['truck']}")
        print(f"   📊 Total:      {summary.get('total', 'N/A')}")

        meta = results["metadata"]
        print(f"\n📹 Video Info:")
        print(f"   Resolution: {meta['resolution']}")
        print(f"   FPS:        {meta['fps']}")
        print(f"   Duration:   {meta['video_duration']:.1f}s")
        print(f"   Frames:     {meta['total_frames']}")
        print(f"   Processed:  {meta['processed_frames']}")

        # Show timeline (first 5 seconds)
        timeline = results.get("timeline", [])
        if timeline:
            print(f"\n⏱  Timeline (first 5 seconds):")
            for entry in timeline[:5]:
                print(f"   {entry['second']}s: car={entry['car']} moto={entry['motorcycle']} bus={entry['bus']} truck={entry['truck']}")

        return results

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ Error after {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("🚗 Vehicle Detection + Tracking Test")
    print("=" * 60)

    videos = ["test1lan.mp4", "test2lan.mp4"]
    all_results = {}

    for video in videos:
        result = run_test(video)
        all_results[video] = result

    # Final comparison
    print(f"\n{'='*60}")
    print("📋 COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"{'Video':<20} {'Car':>5} {'Moto':>5} {'Bus':>5} {'Truck':>5} {'Total':>6}")
    print(f"{'-'*20} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*6}")

    for video, result in all_results.items():
        if result:
            s = result["summary"]
            print(f"{video:<20} {s['car']:>5} {s['motorcycle']:>5} {s['bus']:>5} {s['truck']:>5} {s.get('total', 0):>6}")
        else:
            print(f"{video:<20} {'FAILED':>30}")
