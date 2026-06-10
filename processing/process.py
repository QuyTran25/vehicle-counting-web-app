"""
Core video processing engine: YOLO Detection + ByteTrack + LineZone (counting logic)
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import cv2 # type: ignore
import numpy as np # type: ignore
import supervision as sv # type: ignore
from ultralytics import YOLO # type: ignore

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import (
    MODEL_NAME,
    CONF_THRESHOLD,
    IOU_THRESHOLD,
    COUNT_CONF_MIN,
    CLASS_IDS,
    VEHICLE_CLASSES,
    MODELS_DIR,
    LINE_START,
    LINE_END,
    LINE_AUTO_Y_RATIO,
    TRACK_LOST_BUFFER,
    TRACK_ACTIVATION_THRESHOLD,
    TRACK_MINIMUM_MATCHING,
    TRACK_MINIMUM_CONSECUTIVE,
    OUTPUT_VIDEO_CODEC,
    OUTPUT_VIDEO_QUALITY,
)
from processing.utils import (
    validate_video,
    get_video_info,
    video_frame_generator,
    create_video_writer,
)


def compute_line_position(width: int, height: int) -> Tuple[sv.Point, sv.Point]:
    """
    Tính tọa độ vạch kẻ dựa trên resolution video.
    Nếu cấu hình LINE_START/LINE_END hợp lệ với khung hình hiện tại thì dùng giá trị đó.
    Ngược lại, vị trí mặc định sẽ được đặt tại một tỉ lệ chiều cao video để phù hợp hơn với làn đường.

    Args:
        width: Chiều rộng video
        height: Chiều cao video

    Returns:
        Tuple[sv.Point, sv.Point]: Điểm đầu và cuối của vạch
    """
    if 0 <= LINE_START[0] <= width and 0 <= LINE_START[1] <= height \
       and 0 <= LINE_END[0] <= width and 0 <= LINE_END[1] <= height:
        return sv.Point(x=LINE_START[0], y=LINE_START[1]), sv.Point(x=LINE_END[0], y=LINE_END[1])

    y = int(height * LINE_AUTO_Y_RATIO)
    return sv.Point(x=0, y=y), sv.Point(x=width, y=y)


class VehicleDetector:
    """
    Main vehicle detection engine combining YOLO + ByteTrack + LineZone.

    Quy tắc đếm (theo DESIGN.md):
    - Chỉ đếm khi tâm bounding box cắt qua LineZone.
    - Mỗi track_id chỉ được đếm 1 lần (counted_ids).
    - Ghi lại direction ('in' hoặc 'out') cho từng sự kiện.
    """

    def __init__(self):
        """Initialize YOLO model. Tracker được khởi tạo sau khi biết fps thực của video."""
        self.model = None
        self.tracker = None
        self._init_model()

    # ──────────────────────────────────────────
    # Initialization helpers
    # ──────────────────────────────────────────

    def _init_model(self):
        """Load YOLO model from local models/ folder or download if missing."""
        model_path = MODELS_DIR / MODEL_NAME
        if not model_path.exists():
            print(f"📥 Downloading {MODEL_NAME}...")
            self.model = YOLO(MODEL_NAME)
        else:
            print(f"📂 Loading {MODEL_NAME} from local...")
            self.model = YOLO(str(model_path))
        print("✅ Model loaded successfully!")

    def _init_tracker(self, fps: float):
        """
        Khởi tạo ByteTrack với fps thực của video.
        Quan trọng: frame_rate phải đúng để lost_track_buffer tính thời gian chính xác.
        """
        self.tracker = sv.ByteTrack(
            lost_track_buffer=TRACK_LOST_BUFFER,
            track_activation_threshold=TRACK_ACTIVATION_THRESHOLD,
            minimum_matching_threshold=TRACK_MINIMUM_MATCHING,
            minimum_consecutive_frames=TRACK_MINIMUM_CONSECUTIVE,
            frame_rate=int(round(fps)),  # dùng fps thực, không hardcode 30
        )
        print(f"🎯 ByteTrack initialized @ {fps:.1f}fps | buffer={TRACK_LOST_BUFFER}f "
              f"({TRACK_LOST_BUFFER/fps:.1f}s) | activation={TRACK_ACTIVATION_THRESHOLD}")

    # ──────────────────────────────────────────
    # Detection & Tracking
    # ──────────────────────────────────────────

    def detect_frame(self, frame) -> sv.Detections:
        """
        Phát hiện phương tiện trong 1 frame bằng YOLO.

        Args:
            frame: Input frame (numpy array)

        Returns:
            sv.Detections: Detection results
        """
        results = self.model(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            classes=CLASS_IDS,
            verbose=False,
        )
        detections = sv.Detections.from_ultralytics(results[0])
        return detections

    def update_tracker(self, detections: sv.Detections) -> sv.Detections:
        """
        Cập nhật ByteTrack, gán track_id cho từng detection.

        Args:
            detections: YOLO detections

        Returns:
            sv.Detections: Detections có tracker_id
        """
        detections = self.tracker.update_with_detections(detections)
        return detections

    # ──────────────────────────────────────────
    # Main processing pipeline
    # ──────────────────────────────────────────

    def process_video(
        self,
        input_path: str,
        output_path: str,
        json_output_path: str,
        callback=None,
    ) -> Dict[str, Any]:
        """
        Xử lý video frame-by-frame: detect → track → count (LineZone) → export.

        Logic đếm:
            if object.center crosses line AND track_id not in counted_ids:
                count += 1
                counted_ids.add(track_id)

        Args:
            input_path: Đường dẫn video đầu vào
            output_path: Đường dẫn lưu video output (đã vẽ annotations)
            json_output_path: Đường dẫn lưu kết quả JSON
            callback: Hàm callback báo tiến trình(frame_num, total_frames, progress%)

        Returns:
            dict: Kết quả gồm metadata, summary, timeline, events
        """
        # ── 1. Validate video ──
        is_valid, error_msg = validate_video(input_path)
        if not is_valid:
            raise ValueError(f"Invalid video: {error_msg}")

        # ── 2. Get video info ──
        video_info = get_video_info(input_path)
        width = video_info["width"]
        height = video_info["height"]
        fps = video_info["fps"]
        total_frames = video_info["frame_count"]
        print(f"\n📹 Video: {video_info['resolution']} @ {fps:.1f}fps, {video_info['duration']:.1f}s ({total_frames} frames)")

        # ── 3. Initialize video writer ──
        writer = create_video_writer(
            output_path,
            fps,
            width,
            height,
            codec=OUTPUT_VIDEO_CODEC,
            quality=OUTPUT_VIDEO_QUALITY,
        )

        # ── 4. Khởi tạo tracker với fps thực (quan trọng!) ──
        self._init_tracker(fps)

        # ── 5. Setup LineZone (vạch kẻ) ──
        line_start, line_end = compute_line_position(width, height)
        # Dùng BOTTOM_CENTER: điểm chân xe ổn định hơn tâm bbox khi bị che khuất
        line_zone = sv.LineZone(
            start=line_start,
            end=line_end,
            triggering_anchors=[sv.Position.BOTTOM_CENTER],
        )
        line_annotator = sv.LineZoneAnnotator(
            thickness=3,
            color=sv.Color.from_hex("#FFFF00"),
            text_thickness=2,
            text_scale=1.0,
        )
        print(f"📏 LineZone: ({line_start.x},{line_start.y}) → ({line_end.x},{line_end.y}) | anchor=BOTTOM_CENTER")

        # ── 6. Setup annotators ──
        box_annotator = sv.BoundingBoxAnnotator(thickness=2)
        label_annotator = sv.LabelAnnotator(
            text_scale=0.28,       # nhỏ hơn để không che xe phía sau
            text_thickness=1,
            text_padding=2,
        )
        trace_annotator = sv.TraceAnnotator(
            trace_length=40,
            thickness=2,
            color_lookup=sv.ColorLookup.TRACK,
        )

        # ── 7. Counting state ──
        counted_ids: set = set()          # track_id đã được đếm (không đếm trùng)
        seen_track_ids: set = set()      # tất cả track_id đã xuất hiện
        all_events: List[dict] = []       # danh sách sự kiện crossing
        timeline_dict: Dict[int, dict] = {}  # second -> {car, motorcycle, bus, truck}

        frame_number = 0
        try:
            for frame_number, frame in video_frame_generator(input_path):

                # ── A. Detect & Track ──
                detections = self.detect_frame(frame)
                tracked = self.update_tracker(detections)

                for i in range(len(tracked)):
                    if tracked.tracker_id is None:
                        continue
                    track_id = int(tracked.tracker_id[i])
                    seen_track_ids.add(track_id)

                # ── B. LineZone trigger (kiểm tra xe cắt vạch) ──
                # supervision 0.21: trigger() trả về tuple (crossed_in_mask, crossed_out_mask)
                # crossed_in_mask[i] = True nếu detection i đi vào (cross line từ dưới lên)
                # crossed_out_mask[i] = True nếu detection i đi ra (cross line từ trên xuống)
                crossed_in_mask, crossed_out_mask = line_zone.trigger(detections=tracked)

                # ── C. Ghi sự kiện crossing ──
                timestamp = frame_number / fps
                second = int(timestamp)

                for i in range(len(tracked)):
                    if tracked.tracker_id is None:
                        continue
                    track_id = int(tracked.tracker_id[i])
                    class_id = int(tracked.class_id[i])
                    class_name = VEHICLE_CLASSES.get(class_id, "unknown")
                    confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0

                    # Kiểm tra: xe có cắt vạch không? (in HOẶC out)
                    is_crossed_in = bool(crossed_in_mask[i]) if i < len(crossed_in_mask) else False
                    is_crossed_out = bool(crossed_out_mask[i]) if i < len(crossed_out_mask) else False

                    if (is_crossed_in or is_crossed_out) and (track_id not in counted_ids):
                        # Lọc confidence thấp: tránh false positive khi đếm
                        if confidence < COUNT_CONF_MIN:
                            continue
                        # Chỉ đếm lần đầu tiên
                        counted_ids.add(track_id)
                        direction = "in" if is_crossed_in else "out"

                        # Ghi event
                        all_events.append({
                            "frame": frame_number,
                            "timestamp": round(timestamp, 3),
                            "track_id": track_id,
                            "class": class_name,
                            "confidence": round(confidence, 4),
                            "direction": direction,
                        })

                        # Cập nhật timeline
                        if second not in timeline_dict:
                            timeline_dict[second] = {
                                "second": second,
                                "car": 0,
                                "motorcycle": 0,
                                "bus": 0,
                                "truck": 0,
                            }
                        if class_name in timeline_dict[second]:
                            timeline_dict[second][class_name] += 1

                # ── D. Annotate frame ──
                annotated = frame.copy()

                # 1) Trace (vẽ đường đi)
                annotated = trace_annotator.annotate(scene=annotated, detections=tracked)

                # 2) Bounding boxes
                annotated = box_annotator.annotate(scene=annotated, detections=tracked)

                # 3) Labels: show compact ID + class only to avoid occluding vehicles
                labels = []
                for i in range(len(tracked)):
                    tid = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else -1
                    cid = int(tracked.class_id[i])
                    cname = VEHICLE_CLASSES.get(cid, "?")
                    is_counted = " ✓" if tid in counted_ids else ""
                    labels.append(f"#{tid} {cname}{is_counted}")

                if labels:
                    annotated = label_annotator.annotate(
                        scene=annotated, detections=tracked, labels=labels
                    )

                # 4) LineZone (vạch kẻ + bộ đếm IN/OUT)
                # supervision 0.21: dùng frame= thay vì scene=
                annotated = line_annotator.annotate(
                    frame=annotated, line_counter=line_zone
                )

                # ── E. Ghi frame ra video ──
                writer.write(annotated)

                # ── F. Progress callback ──
                if callback and total_frames > 0:
                    progress = int((frame_number / total_frames) * 100)
                    callback(frame_number, total_frames, progress)

                if (frame_number + 1) % 60 == 0:
                    progress = int((frame_number / total_frames) * 100) if total_frames > 0 else 0
                    print(f"  ⏳ {progress}% — frame {frame_number + 1}/{total_frames} | Crossed: {len(counted_ids)}")

        finally:
            writer.release()
            print(f"\n✅ Video processing complete! Total crossed: {len(all_events)} events, {len(counted_ids)} unique vehicles")
            print(f"   Observed track IDs: {len(seen_track_ids)}")

        # ── 7. Build results JSON ──
        # Timeline: điền các giây còn thiếu với giá trị 0
        timeline = []
        if timeline_dict:
            for sec in range(max(timeline_dict.keys()) + 1):
                if sec in timeline_dict:
                    timeline.append(timeline_dict[sec])
                else:
                    timeline.append({"second": sec, "car": 0, "motorcycle": 0, "bus": 0, "truck": 0})

        summary = self._compute_summary(all_events)

        results = {
            "metadata": {
                "video_duration": round(video_info["duration"], 3),
                "fps": round(fps, 3),
                "total_frames": total_frames,
                "resolution": video_info["resolution"],
                "processed_frames": frame_number + 1,
                "line_position": {
                    "start": [line_start.x, line_start.y],
                    "end": [line_end.x, line_end.y],
                },
            },
            "summary": summary,
            "timeline": timeline,
            "events": all_events,
        }

        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"📊 JSON saved to: {json_output_path}")
        print(f"🎬 Video saved to: {output_path}")
        return results

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _compute_summary(self, events: List[dict]) -> dict:
        """
        Tính tổng số xe mỗi loại đã đi qua vạch kẻ.
        Mỗi track_id chỉ được tính 1 lần (đã được đảm bảo bởi counted_ids).

        Args:
            events: Danh sách crossing events (đã lọc chỉ xe qua vạch)

        Returns:
            dict: Tổng số xe mỗi loại + total
        """
        summary = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}
        seen_ids = set()

        for event in events:
            tid = event["track_id"]
            cls = event["class"]
            if tid not in seen_ids:
                seen_ids.add(tid)
                if cls in summary:
                    summary[cls] += 1

        summary["total"] = sum(summary.values())
        return summary


# ──────────────────────────────────────────
# Standalone function (called by main.py & test_videos.py)
# ──────────────────────────────────────────

def process_video_file(
    input_path: str,
    output_path: str,
    json_output_path: str,
    callback=None,
) -> Dict:
    """
    Hàm đơn lẻ để xử lý video — được gọi từ web backend và CLI.

    Args:
        input_path: Đường dẫn video đầu vào
        output_path: Đường dẫn video output (đã annotate)
        json_output_path: Đường dẫn JSON kết quả
        callback: Optional progress callback(frame_num, total, progress%)

    Returns:
        dict: Kết quả xử lý
    """
    detector = VehicleDetector()
    results = detector.process_video(input_path, output_path, json_output_path, callback)
    return results


# ──────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    """
    Chạy thủ công qua command-line:
        python processing/process.py uploads/test1lan.mp4 outputs/test1lan_output.mp4 outputs/test1lan_result.json
    """
    if len(sys.argv) < 4:
        print("Usage: python processing/process.py <input_video> <output_video> <output_json>")
        print("Example: python processing/process.py uploads/test1lan.mp4 outputs/out.mp4 outputs/result.json")
        sys.exit(1)

    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_json = sys.argv[3]

    print(f"🚗 Vehicle Counting — LineZone Edition")
    print(f"   Input : {input_video}")
    print(f"   Output: {output_video}")
    print(f"   JSON  : {output_json}")

    try:
        results = process_video_file(input_video, output_video, output_json)
        print(f"\n✅ Done!")
        print(f"   Summary: {results['summary']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)