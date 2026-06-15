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


def compute_split_lines(width: int, height: int) -> Tuple[Tuple[sv.Point, sv.Point], Tuple[sv.Point, sv.Point]]:
    """
    Tính tọa độ cho 2 vạch kẻ:
    - line_out (bên trái, hướng đi xuống): Y ở vị trí 72% chiều cao (thấp).
    - line_in (bên phải, hướng đi lên): Y ở vị trí 35% chiều cao (cao).
    Cho phép gối đầu (overlap) ở giữa để tránh sót xe đi sát dải phân cách do góc nhìn phối cảnh.
    """
    divider_x_out = int(width * 0.48)
    divider_x_in = int(width * 0.46) # dải phân cách chéo về trái khi ở trên cao
    
    y_out = int(height * 0.72)
    y_in = int(height * 0.35)
    
    # Left line (OUT): kéo dài qua dải phân cách một chút (+15px)
    line_out_start = sv.Point(x=0, y=y_out)
    line_out_end = sv.Point(x=divider_x_out + 15, y=y_out)
    
    # Right line (IN): kéo dài sang trái qua dải phân cách một chút (-25px)
    line_in_start = sv.Point(x=divider_x_in - 25, y=y_in)
    line_in_end = sv.Point(x=width, y=y_in)
    
    return (line_out_start, line_out_end), (line_in_start, line_in_end)


def draw_custom_line_zone(frame, start, end, label, count, color=(0, 255, 255), is_in_line=False):
    """
    Vẽ vạch kẻ và nhãn chỉ số IN hoặc OUT riêng biệt cho từng lane.
    """
    # Vẽ đường line chính
    cv2.line(frame, (start.x, start.y), (end.x, end.y), color, 3, cv2.LINE_AA)
    
    # Vẽ các đầu tròn cho vạch
    cv2.circle(frame, (start.x, start.y), 6, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(frame, (start.x, start.y), 4, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (end.x, end.y), 6, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(frame, (end.x, end.y), 4, color, -1, cv2.LINE_AA)
    
    # Chuẩn bị chữ hiển thị
    text = f"{label}: {count}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.75
    text_thickness = 2
    
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, text_thickness)
    
    # Tính tọa độ trung tâm của vạch
    center_x = (start.x + end.x) // 2
    center_y = (start.y + end.y) // 2
    
    if is_in_line:
        # Đẩy chữ lên phía trên nếu là line IN
        box_y1 = center_y - text_height - 12
        box_y2 = center_y - 2
    else:
        # Đẩy chữ xuống phía dưới nếu là line OUT
        box_y1 = center_y + 2
        box_y2 = center_y + text_height + 12
        
    box_x1 = center_x - text_width // 2 - 8
    box_x2 = center_x + text_width // 2 + 8
    
    # Vẽ hình nền nhãn
    cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), color, -1)
    # Vẽ chữ màu đen
    cv2.putText(
        frame, 
        text, 
        (box_x1 + 8, box_y2 - 5), 
        font, 
        font_scale, 
        (0, 0, 0), 
        text_thickness, 
        cv2.LINE_AA
    )


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

        # ── 5. Setup LineZones (vạch kẻ chia đôi làn) ──
        (line_out_start, line_out_end), (line_in_start, line_in_end) = compute_split_lines(width, height)
        
        # Line zone cho xe đi xuống (bên trái)
        line_zone_out = sv.LineZone(
            start=line_out_start,
            end=line_out_end,
            triggering_anchors=[sv.Position.BOTTOM_CENTER, sv.Position.CENTER],
        )
        # Line zone cho xe đi lên (bên phải)
        line_zone_in = sv.LineZone(
            start=line_in_start,
            end=line_in_end,
            triggering_anchors=[sv.Position.BOTTOM_CENTER, sv.Position.CENTER],
        )
        
        line_annotator = sv.LineZoneAnnotator(
            thickness=3,
            color=sv.Color.from_hex("#FFFF00"),
            text_thickness=2,
            text_scale=1.0,
        )
        print(f"[LineZone] Out (left): ({line_out_start.x},{line_out_start.y}) -> ({line_out_end.x},{line_out_end.y})")
        print(f"[LineZone] In (right): ({line_in_start.x},{line_in_start.y}) -> ({line_in_end.x},{line_in_end.y})")

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

                # ── B. LineZone trigger (kiểm tra xe cắt vạch ở cả 2 LineZone) ──
                crossed_in_mask_out, crossed_out_mask_out = line_zone_out.trigger(detections=tracked)
                crossed_in_mask_in, crossed_out_mask_in = line_zone_in.trigger(detections=tracked)

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

                    # Kiểm tra: xe có cắt vạch không? (in HOẶC out trên cả 2 LineZone)
                    is_in_crossed_in = bool(crossed_in_mask_in[i]) if i < len(crossed_in_mask_in) else False
                    is_in_crossed_out = bool(crossed_out_mask_in[i]) if i < len(crossed_out_mask_in) else False
                    
                    is_out_crossed_in = bool(crossed_in_mask_out[i]) if i < len(crossed_in_mask_out) else False
                    is_out_crossed_out = bool(crossed_out_mask_out[i]) if i < len(crossed_out_mask_out) else False

                    is_crossed = False
                    direction = None
                    
                    if is_in_crossed_in or is_in_crossed_out:
                        is_crossed = True
                        direction = "in" if is_in_crossed_in else "out"
                    elif is_out_crossed_in or is_out_crossed_out:
                        is_crossed = True
                        direction = "in" if is_out_crossed_in else "out"

                    if is_crossed and (track_id not in counted_ids):
                        # Lọc confidence thấp: tránh false positive khi đếm
                        if confidence < COUNT_CONF_MIN:
                            continue
                        # Chỉ đếm lần đầu tiên
                        counted_ids.add(track_id)

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

                # 4) LineZones (vạch kẻ + vẽ nhãn IN/OUT riêng biệt cho từng lane)
                # Left line: chỉ vẽ OUT
                draw_custom_line_zone(
                    annotated, 
                    line_out_start, 
                    line_out_end, 
                    label="LINE OUT", 
                    count=line_zone_out.out_count, 
                    color=(0, 255, 255), 
                    is_in_line=False
                )
                # Right line: chỉ vẽ IN
                draw_custom_line_zone(
                    annotated, 
                    line_in_start, 
                    line_in_end, 
                    label="LINE IN", 
                    count=line_zone_in.in_count, 
                    color=(0, 255, 255), 
                    is_in_line=True
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
                    "line_out": {
                        "start": [line_out_start.x, line_out_start.y],
                        "end": [line_out_end.x, line_out_end.y],
                    },
                    "line_in": {
                        "start": [line_in_start.x, line_in_start.y],
                        "end": [line_in_end.x, line_in_end.y],
                    }
                },
            },
            "summary": summary,
            "timeline": timeline,
            "events": all_events,
        }

        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"[JSON] Saved to: {json_output_path}")
        print(f"[Video] Saved to: {output_path}")
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