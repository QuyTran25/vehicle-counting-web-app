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
    OUTPUTS_DIR,
    LINE_START,
    LINE_END,
    LINE_AUTO_Y_RATIO,
    LINE_ANCHOR,
    TRACK_LOST_BUFFER,
    TRACK_ACTIVATION_THRESHOLD,
    TRACK_MINIMUM_MATCHING,
    TRACK_MINIMUM_CONSECUTIVE,
    OUTPUT_VIDEO_CODEC,
    OUTPUT_VIDEO_QUALITY,
    # New config parameters
    MIN_BOX_AREA,
    MAX_BOX_AREA,
    MIN_BOX_WIDTH,
    MIN_BOX_HEIGHT,
    MAX_ASPECT_RATIO,
    MIN_ASPECT_RATIO,
    IS_SINGLE_LANE,
)
from processing.utils import (
    validate_video,
    get_video_info,
    video_frame_generator,
    create_video_writer,
)


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION FILTERS - Loại bỏ false detections
# ─────────────────────────────────────────────────────────────────────────────

def filter_detections(detections: sv.Detections) -> sv.Detections:
    """
    Lọc detections dựa trên size và aspect ratio.
    
    Loại bỏ:
    - Boxes quá nhỏ (noise)
    - Boxes quá lớn (anomalies)
    - Aspect ratio không hợp lệ cho xe
    
    Args:
        detections: YOLO detections
        
    Returns:
        Filtered detections
    """
    if len(detections) == 0:
        return detections
    
    # Lấy thông tin boxes
    xyxy = detections.xyxy  # [x1, y1, x2, y2]
    
    # Tính width, height, area
    widths = xyxy[:, 2] - xyxy[:, 0]
    heights = xyxy[:, 3] - xyxy[:, 1]
    areas = widths * heights
    
    # Tính aspect ratio (width / height)
    with np.errstate(divide='ignore', invalid='ignore'):
        aspect_ratios = widths / heights
        aspect_ratios = np.nan_to_num(aspect_ratios, nan=0, posinf=0, neginf=0)
    
    # Tạo mask cho detections hợp lệ
    valid_mask = (
        (areas >= MIN_BOX_AREA) &          # Diện tích >= ngưỡng tối thiểu
        (areas <= MAX_BOX_AREA) &           # Diện tích <= ngưỡng tối đa
        (widths >= MIN_BOX_WIDTH) &         # Chiều rộng >= ngưỡng
        (heights >= MIN_BOX_HEIGHT) &       # Chiều cao >= ngưỡng
        (aspect_ratios >= MIN_ASPECT_RATIO) &  # AR >= tối thiểu
        (aspect_ratios <= MAX_ASPECT_RATIO)    # AR <= tối đa
    )
    
    # Áp dụng filter
    filtered = detections[valid_mask]
    
    # Debug log số lượng bị loại
    removed = len(detections) - len(filtered)
    if removed > 0:
        print(f"   [Filter] Removed {removed}/{len(detections)} detections (size/aspect invalid)")
    
    return filtered


def compute_split_lines(width: int, height: int) -> Tuple[Tuple[sv.Point, sv.Point], Tuple[sv.Point, sv.Point]]:
    """
    Tính tọa độ cho 2 vạch kẻ:
    - line_out (bên trái, hướng đi xuống): Y ở vị trí 72% chiều cao.
    - line_in (bên phải, hướng đi lên): Y ở vị trí 55% chiều cao.
    Hạ thấp LINE IN (từ 35% xuống 55%) để đếm xe khi chúng còn đủ lớn, tránh mất tracking do xe đi quá xa và bị nhỏ lại.
    """
    divider_x_out = int(width * 0.48)
    divider_x_in = int(width * 0.46) # dải phân cách chéo về trái khi ở trên cao
    
    y_out = int(height * 0.72)
    y_in = int(height * 0.55)  # Hạ thấp từ 0.35 -> 0.55 để đếm chính xác hơn
    
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
            sv.Detections: Detection results (filtered)
        """
        results = self.model(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            classes=CLASS_IDS,
            verbose=False,
        )
        detections = sv.Detections.from_ultralytics(results[0])
        
        # Áp dụng filter
        detections = filter_detections(detections)
        
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
        single_lane: bool = False,
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
            single_lane: Override config IS_SINGLE_LANE nếu True

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
        
        # Live paths
        task_id = Path(json_output_path).name.replace("_result.json", "")
        live_json_path = OUTPUTS_DIR / f"{task_id}_live.json"
        live_img_path = OUTPUTS_DIR / f"{task_id}_live.jpg"

        # ── 4. Khởi tạo tracker với fps thực (quan trọng!) ──
        self._init_tracker(fps)

        # ── 5. Setup LineZones ──
        # ── 5. Setup LineZones ──
        # use_single_lane = True → chỉ 1 line cho đường 1 chiều
        # use_single_lane = False → 2 line (Left=OUT, Right=IN)
        use_single_lane = single_lane or IS_SINGLE_LANE
        
        if use_single_lane:
            # 1 LineZone duy nhất ở giữa
            line_zone_out = sv.LineZone(
                start=sv.Point(x=0, y=int(height*0.5)),
                end=sv.Point(x=width, y=int(height*0.5)),
                triggering_anchors=[LINE_ANCHOR],
            )
            line_zone_in = None # Không dùng
        else:
            # Dual lines
            (line_out_start, line_out_end), (line_in_start, line_in_end) = compute_split_lines(width, height)
            line_zone_out = sv.LineZone(
                start=line_out_start,
                end=line_out_end,
                triggering_anchors=[LINE_ANCHOR],
            )
            line_zone_in = sv.LineZone(
                start=line_in_start,
                end=line_in_end,
                triggering_anchors=[LINE_ANCHOR],
            )
        
        line_annotator = sv.LineZoneAnnotator(
            thickness=3,
            color=sv.Color.from_hex("#FFFF00"),
            text_thickness=2,
            text_scale=1.0,
        )
        print(f"[LineZone] Mode: {'SINGLE LANE' if use_single_lane else 'DUAL LANE'}")
        if not use_single_lane:
            print(f"[LineZone] Out (left): ({line_out_start.x},{line_out_start.y}) -> ({line_out_end.x},{line_out_end.y})")
            print(f"[LineZone] In (right): ({line_in_start.x},{line_in_start.y}) -> ({line_in_end.x},{line_in_end.y})")
        else:
            print(f"[LineZone] Single line at y={int(height*0.5)}")

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
        counted_in_ids: set = set()      # track_id đã đếm ở LINE IN
        counted_out_ids: set = set()     # track_id đã đếm ở LINE OUT
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

                # ── B. LineZone trigger ──
                crossed_in_mask_out, crossed_out_mask_out = line_zone_out.trigger(detections=tracked)
                if line_zone_in is not None:
                    crossed_in_mask_in, crossed_out_mask_in = line_zone_in.trigger(detections=tracked)
                else:
                    crossed_in_mask_in = np.array([], dtype=bool)
                    crossed_out_mask_in = np.array([], dtype=bool)

                # ── C. Ghi sự kiện crossing (Tách biệt logic đếm) ──
                timestamp = frame_number / fps
                second = int(timestamp)

                for i in range(len(tracked)):
                    if tracked.tracker_id is None:
                        continue
                    track_id = int(tracked.tracker_id[i])
                    class_id = int(tracked.class_id[i])
                    class_name = VEHICLE_CLASSES.get(class_id, "unknown")
                    confidence = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0

                    # Check crossing
                    # Check crossing for each line zone (either direction of crossing is valid since lanes are physically split)
                    is_crossed_in = (
                        (bool(crossed_in_mask_in[i]) or bool(crossed_out_mask_in[i]))
                        if i < len(crossed_in_mask_in) and i < len(crossed_out_mask_in) else False
                    )
                    is_crossed_out = (
                        (bool(crossed_in_mask_out[i]) or bool(crossed_out_mask_out[i]))
                        if i < len(crossed_in_mask_out) and i < len(crossed_out_mask_out) else False
                    )

                    # 1. Đếm LINE IN (Right lane - UP/IN traffic)
                    if is_crossed_in and confidence >= COUNT_CONF_MIN:
                        if track_id not in counted_in_ids:
                            counted_in_ids.add(track_id)
                            all_events.append({
                                "frame": frame_number,
                                "timestamp": round(timestamp, 3),
                                "track_id": track_id,
                                "class": class_name,
                                "confidence": round(confidence, 4),
                                "direction": "in",
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

                    # 2. Đếm LINE OUT (Left lane - DOWN/OUT traffic)
                    if is_crossed_out and confidence >= COUNT_CONF_MIN:
                        if track_id not in counted_out_ids:
                            counted_out_ids.add(track_id)
                            all_events.append({
                                "frame": frame_number,
                                "timestamp": round(timestamp, 3),
                                "track_id": track_id,
                                "class": class_name,
                                "confidence": round(confidence, 4),
                                "direction": "out",
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
                    is_counted_in = " IN" if tid in counted_in_ids else ""
                    is_counted_out = " OUT" if tid in counted_out_ids else ""
                    labels.append(f"#{tid} {cname}{is_counted_in}{is_counted_out}")

                if labels:
                    annotated = label_annotator.annotate(
                        scene=annotated, detections=tracked, labels=labels
                    )

                # 4) LineZones (vạch kẻ + vẽ nhãn IN/OUT riêng biệt cho từng lane)
                if use_single_lane:
                    draw_custom_line_zone(
                        annotated, 
                        sv.Point(x=0, y=int(height*0.5)), 
                        sv.Point(x=width, y=int(height*0.5)), 
                        label="LINE", 
                        count=len(counted_in_ids) + len(counted_out_ids), 
                        color=(0, 255, 255), 
                        is_in_line=True
                    )
                else:
                    # Dual lines
                    draw_custom_line_zone(
                        annotated, 
                        line_out_start, 
                        line_out_end, 
                        label="LINE OUT", 
                        count=len(counted_out_ids), 
                        color=(0, 255, 255), 
                        is_in_line=False
                    )
                    draw_custom_line_zone(
                        annotated, 
                        line_in_start, 
                        line_in_end, 
                        label="LINE IN", 
                        count=len(counted_in_ids), 
                        color=(0, 255, 255), 
                        is_in_line=True
                    )

                # ── E. Ghi frame ra video ──
                writer.write(annotated)
                
                # ── E2. Export live frames/stats ──
                if (frame_number + 1) % 5 == 0: # Every 5 frames for stream
                    try:
                        # Save image
                        cv2.imwrite(str(live_img_path), annotated)
                        
                        # Build live results dict
                        live_timeline = []
                        if timeline_dict:
                            for sec in range(max(timeline_dict.keys()) + 1):
                                if sec in timeline_dict:
                                    live_timeline.append(timeline_dict[sec])
                                else:
                                    live_timeline.append({"second": sec, "car": 0, "motorcycle": 0, "bus": 0, "truck": 0})
                        
                        curr_duration = (frame_number + 1) / fps if fps > 0 else 0.0
                        live_summary = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}
                        for evt in all_events:
                            cls = evt["class"]
                            if cls in live_summary:
                                live_summary[cls] += 1
                        live_summary["total"] = sum(live_summary.values())
                        
                        live_results = {
                            "metadata": {
                                "video_duration": round(curr_duration, 3),
                                "fps": round(fps, 3),
                                "total_frames": total_frames,
                                "resolution": f"{width}x{height}",
                                "processed_frames": frame_number + 1,
                            },
                            "summary": live_summary,
                            "timeline": live_timeline,
                            "events": all_events,
                        }
                        
                        with open(live_json_path, "w", encoding="utf-8") as f:
                            json.dump(live_results, f, ensure_ascii=False)
                    except Exception:
                        pass

                # ── F. Progress callback ──
                if callback and total_frames > 0:
                    progress = int((frame_number / total_frames) * 100)
                    callback(frame_number, total_frames, progress)

                if (frame_number + 1) % 60 == 0:
                    progress = int((frame_number / total_frames) * 100) if total_frames > 0 else 0
                    print(f"  ⏳ {progress}% — frame {frame_number + 1}/{total_frames} | IN: {len(counted_in_ids)} | OUT: {len(counted_out_ids)}")

        finally:
            writer.release()
            # Cleanup live files
            live_json_path.unlink(missing_ok=True)
            live_img_path.unlink(missing_ok=True)
            
            total_crossed = len(counted_in_ids) + len(counted_out_ids)
            print(f"\n✅ Video processing complete! Total crossed: {len(all_events)} events, IN={len(counted_in_ids)} OUT={len(counted_out_ids)}")
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
            },
            "summary": summary,
            "timeline": timeline,
            "events": all_events,
        }
        
        if not use_single_lane:
            results["metadata"]["line_position"] = {
                "line_out": {
                    "start": [line_out_start.x, line_out_start.y],
                    "end": [line_out_end.x, line_out_end.y],
                },
                "line_in": {
                    "start": [line_in_start.x, line_in_start.y],
                    "end": [line_in_end.x, line_in_end.y],
                }
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
        Mỗi track_id được phép đếm 2 lần (1 lần IN, 1 lần OUT) vì dùng 2 bộ đếm riêng (counted_in_ids & counted_out_ids).

        Args:
            events: Danh sách crossing events (đã lọc chỉ xe qua vạch)

        Returns:
            dict: Tổng số xe mỗi loại + total
        """
        summary = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}

        # Đếm tất cả events (mỗi event là 1 lần cắt vạch, direction riêng)
        # Không cần deduplicate track_id vì counted_in_ids/counted_out_ids đã chống trùng
        for event in events:
            cls = event["class"]
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
    single_lane: bool = False,
) -> Dict:
    """
    Hàm đơn lẻ để xử lý video — được gọi từ web backend và CLI.

    Args:
        input_path: Đường dẫn video đầu vào
        output_path: Đường dẫn video output (đã annotate)
        json_output_path: Đường dẫn JSON kết quả
        callback: Optional progress callback(frame_num, total, progress%)
        single_lane: Override mode to single lane if True

    Returns:
        dict: Kết quả xử lý
    """
    detector = VehicleDetector()
    results = detector.process_video(input_path, output_path, json_output_path, callback, single_lane)
    return results


# ──────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    """
    Chạy thủ công qua command-line:
        python processing/process.py uploads/test1lan.mp4 outputs/test1lan_output.mp4 outputs/test1lan_result.json [--single-lane]
    """
    if len(sys.argv) < 4:
        print("Usage: python processing/process.py <input_video> <output_video> <output_json> [--single-lane]")
        print("Example: python processing/process.py uploads/test1lan.mp4 outputs/out.mp4 outputs/result.json --single-lane")
        sys.exit(1)

    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_json = sys.argv[3]
    
    single_lane_flag = "--single-lane" in sys.argv

    print(f"🚗 Vehicle Counting — LineZone Edition")
    print(f"   Input : {input_video}")
    print(f"   Output: {output_video}")
    print(f"   JSON  : {output_json}")
    print(f"   Mode  : {'SINGLE LANE' if single_lane_flag else 'DUAL LANE'}")

    try:
        results = process_video_file(input_video, output_video, output_json, single_lane=single_lane_flag)
        print(f"\n✅ Done!")
        print(f"   Summary: {results['summary']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)