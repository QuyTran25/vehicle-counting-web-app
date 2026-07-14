"""
Chế độ vẽ line thủ công (Manual Line Drawing Mode)
====================================================
QUY TẮC CÔ LẬP (bắt buộc tuân thủ khi maintain file này):
- KHÔNG import, sửa, hay gọi bất kỳ thứ gì liên quan chế độ tự động:
  compute_split_lines(), IS_SINGLE_LANE, LINE_START, LINE_END, LINE_AUTO_Y_RATIO,
  hay hàm process_video() trong process.py.
- CHỈ tái sử dụng phần hạ tầng ổn định: VehicleDetector (model + tracker) và
  draw_custom_line_zone() (hàm vẽ line thuần túy, không phụ thuộc logic đếm).
- Nếu process.py đổi cấu trúc VehicleDetector, chỉ cần sửa file này, không ai
  khác bị ảnh hưởng ngược lại.

Hỗ trợ 1 hoặc 2 line do người dùng vẽ tay (tùy video, không cố định).
Trigger anchor mặc định: BOTTOM_CENTER — đây thực chất là default/khuyến nghị
của chính thư viện supervision cho bài toán line-crossing (không phải CENTER),
theo issue #844 của roboflow/supervision. Vẫn để config được vì góc camera/
motorbike box vẫn có thể cần CENTER cho vài trường hợp cụ thể.

FIX theo review (xem ghi chú "REVIEW FIX" ở từng chỗ):
1. flip_direction: sv.LineZone xác định in/out dựa theo chiều vẽ start→end.
   User vẽ trái→phải hay phải→trái đều hợp lệ, nên KHÔNG thể tự suy ra đúng-sai
   từ hình học. Field này cho phép đảo nhãn in/out sau khi vẽ (FE hỏi user
   xác nhận hướng bằng mũi tên, set flag nếu user chọn ngược).
2. count_mode: "both" (default) | "in_only" | "out_only" — dùng cho line ở
   đường 1 chiều, tránh false-count khi có nhiễu tracking đi ngược chiều.
3. Confidence smoothing: dùng max confidence trong cửa sổ N frame gần nhất
   của track_id thay vì confidence đúng khoảnh khắc cắt line — line.trigger()
   chỉ true đúng 1 frame, nếu confidence tụt dưới ngưỡng đúng frame đó thì
   mất đếm vĩnh viễn (nguyên nhân chính gây thiếu đếm ở line xa/nhỏ).
"""
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List, Any, Optional

import supervision as sv  # type: ignore
import cv2  # type: ignore

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import (
    VEHICLE_CLASSES,
    COUNT_CONF_MIN,
    OUTPUT_VIDEO_CODEC,
    OUTPUT_VIDEO_QUALITY,
    OUTPUTS_DIR,
)
from processing.process import VehicleDetector, draw_custom_line_zone
from processing.utils import (
    validate_video,
    get_video_info,
    video_frame_generator,
    create_video_writer,
)


MIN_LINES = 1
MAX_LINES = 2
DEFAULT_TRIGGER_ANCHOR = sv.Position.BOTTOM_CENTER
MIN_LINE_LENGTH_PX = 50          # REVIEW FIX #7: line quá ngắn dễ trigger sai
MIN_LINE_SEPARATION_PX = 100     # REVIEW FIX #7: 2 line quá gần dễ double-count
CONFIDENCE_WINDOW = 5            # REVIEW FIX #4: số frame nhìn lại để lấy max confidence
VALID_COUNT_MODES = {"both", "in_only", "out_only"}


class ManualLine:
    """Đại diện 1 line do người dùng vẽ tay trên canvas."""

    def __init__(self, raw: dict, anchor: sv.Position = DEFAULT_TRIGGER_ANCHOR):
        self.id: str = str(raw.get("id") or raw.get("label") or "line")
        self.label: str = str(raw.get("label", self.id))
        self.start = sv.Point(x=int(raw["x1"]), y=int(raw["y1"]))
        self.end = sv.Point(x=int(raw["x2"]), y=int(raw["y2"]))
        self.zone = sv.LineZone(start=self.start, end=self.end, triggering_anchors=[anchor])

        # REVIEW FIX #2: đảo nhãn in/out — vì hướng thật phụ thuộc chiều vẽ
        # start→end, không thể tự suy luận đúng-sai chỉ từ tọa độ.
        self.flip_direction: bool = bool(raw.get("flip_direction", False))

        # REVIEW FIX #3: line 1 chiều chỉ nên đếm 1 hướng, tránh nhiễu tracking
        # đi ngược (vd người đi bộ, xe lùi, artefact của ByteTrack).
        self.count_mode: str = raw.get("count_mode", "both")
        if self.count_mode not in VALID_COUNT_MODES:
            raise ValueError(f"count_mode phải thuộc {VALID_COUNT_MODES}, nhận '{self.count_mode}'")

        self.counted_in_ids: set = set()
        self.counted_out_ids: set = set()

    def length_px(self) -> float:
        return ((self.end.x - self.start.x) ** 2 + (self.end.y - self.start.y) ** 2) ** 0.5

    def midpoint(self) -> tuple:
        return ((self.start.x + self.end.x) / 2, (self.start.y + self.end.y) / 2)

    def resolve_direction(self, raw_direction: str) -> str:
        """Áp dụng flip_direction lên hướng thô mà sv.LineZone trả về."""
        if not self.flip_direction:
            return raw_direction
        return "out" if raw_direction == "in" else "in"

    @property
    def total_count(self) -> int:
        return len(self.counted_in_ids) + len(self.counted_out_ids)

    def to_metadata(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "start": [self.start.x, self.start.y],
            "end": [self.end.x, self.end.y],
            "flip_direction": self.flip_direction,
            "count_mode": self.count_mode,
            "in_count": len(self.counted_in_ids),
            "out_count": len(self.counted_out_ids),
            "total": self.total_count,
        }


def parse_manual_lines(
    raw_lines: List[dict],
    frame_width: int,
    frame_height: int,
    anchor: sv.Position = DEFAULT_TRIGGER_ANCHOR,
) -> List[ManualLine]:
    """
    Validate + build danh sách ManualLine từ config (vd lấy từ DB / API request).
    Bắt buộc 1-2 line — khớp với yêu cầu hiện tại (tùy video, không cố định số lượng).

    REVIEW FIX #7: validate thêm độ dài line tối thiểu, tọa độ nằm trong khung
    hình, và cảnh báo (không raise) nếu 2 line quá gần nhau (dễ double-count
    cùng 1 xe ở 2 line liên tiếp).
    """
    if not raw_lines:
        raise ValueError("Chế độ vẽ thủ công cần ít nhất 1 line.")
    if not (MIN_LINES <= len(raw_lines) <= MAX_LINES):
        raise ValueError(
            f"Chỉ hỗ trợ {MIN_LINES}-{MAX_LINES} line thủ công, nhận được {len(raw_lines)}."
        )

    lines = [ManualLine(rl, anchor) for rl in raw_lines]

    for line in lines:
        for pt in (line.start, line.end):
            if not (0 <= pt.x <= frame_width and 0 <= pt.y <= frame_height):
                raise ValueError(
                    f"Line '{line.label}' có điểm ({pt.x},{pt.y}) nằm ngoài khung hình "
                    f"{frame_width}x{frame_height}."
                )
        if line.length_px() < MIN_LINE_LENGTH_PX:
            raise ValueError(
                f"Line '{line.label}' dài {line.length_px():.0f}px, "
                f"tối thiểu {MIN_LINE_LENGTH_PX}px."
            )

    if len(lines) == 2:
        (x1, y1), (x2, y2) = lines[0].midpoint(), lines[1].midpoint()
        dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if dist < MIN_LINE_SEPARATION_PX:
            print(
                f"[Manual][Warning] 2 line rất gần nhau ({dist:.0f}px < "
                f"{MIN_LINE_SEPARATION_PX}px) — 1 xe có thể bị đếm ở cả 2 line."
            )

    return lines


def process_video_file_manual(
    input_path: str,
    output_path: str,
    json_output_path: str,
    lines: List[dict],
    callback=None,
    trigger_anchor: sv.Position = DEFAULT_TRIGGER_ANCHOR,
) -> Dict[str, Any]:
    """
    Xử lý video với 1-2 line do người dùng vẽ tay.
    Độc lập hoàn toàn với process_video_file() (chế độ tự động) trong process.py.

    Logic đếm: dùng đúng bản chất sv.LineZone — mỗi line tự phân loại hướng
    cắt (in/out) dựa trên phía của line. Khác với chế độ tự động (gộp OR 2
    hướng thành 1 lần đếm cho mỗi lane) vì đây là 2 luồng tính năng độc lập.

    Args:
        input_path: Đường dẫn video đầu vào
        output_path: Đường dẫn video output (đã annotate)
        json_output_path: Đường dẫn JSON kết quả
        lines: Danh sách 1-2 line, mỗi phần tử dạng
               {"id": "L1", "label": "Line A", "x1":.., "y1":.., "x2":.., "y2":..}
               (tọa độ theo resolution GỐC của video, không phải resolution hiển thị canvas)
        callback: Optional progress callback(frame_num, total_frames, progress%)
        trigger_anchor: Điểm trigger trên bounding box (mặc định BOTTOM_CENTER)

    Returns:
        dict: metadata, summary, timeline, events (cùng shape với chế độ tự động
              để dashboard/Chart.js đọc được, chỉ thêm field mới, không đổi field cũ)
    """
    is_valid, error_msg = validate_video(input_path)
    if not is_valid:
        raise ValueError(f"Invalid video: {error_msg}")

    video_info = get_video_info(input_path)
    width, height, fps = video_info["width"], video_info["height"], video_info["fps"]
    total_frames = video_info["frame_count"]

    manual_lines = parse_manual_lines(lines, width, height, trigger_anchor)
    print(f"[Manual] {len(manual_lines)} line(s), anchor={trigger_anchor}")
    for ml in manual_lines:
        flags = []
        if ml.flip_direction:
            flags.append("flipped")
        if ml.count_mode != "both":
            flags.append(ml.count_mode)
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  - {ml.label}: ({ml.start.x},{ml.start.y}) -> ({ml.end.x},{ml.end.y}){flag_str}")

    # REVIEW FIX #4: buffer confidence gần nhất mỗi track_id, dùng max trong
    # cửa sổ CONFIDENCE_WINDOW frame thay vì confidence đúng khoảnh khắc cắt
    # line — trigger() chỉ true đúng 1 frame nên rất dễ mất đếm nếu confidence
    # dao động xuống dưới ngưỡng đúng lúc đó.
    recent_confidence: Dict[int, deque] = {}

    detector = VehicleDetector()      # tái sử dụng: load model YOLO
    detector._init_tracker(fps)       # tái sử dụng: khởi tạo ByteTrack đúng fps thực

    writer = create_video_writer(
        output_path, fps, width, height,
        codec=OUTPUT_VIDEO_CODEC, quality=OUTPUT_VIDEO_QUALITY,
    )

    # Live paths for streaming
    task_id = Path(json_output_path).name.replace("_result.json", "")
    live_json_path = OUTPUTS_DIR / f"{task_id}_live.json"
    live_img_path = OUTPUTS_DIR / f"{task_id}_live.jpg"

    trace_annotator = sv.TraceAnnotator(trace_length=40, thickness=2, color_lookup=sv.ColorLookup.TRACK)
    box_annotator = sv.BoundingBoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.28, text_thickness=1, text_padding=2)
    line_colors = [(0, 255, 255), (255, 128, 0)]  # màu khác nhau nếu có 2 line

    all_events: List[dict] = []
    timeline_dict: Dict[int, dict] = {}
    frame_number = 0

    try:
        for frame_number, frame in video_frame_generator(input_path):
            detections = detector.detect_frame(frame)
            tracked = detector.update_tracker(detections)

            timestamp = frame_number / fps
            second = int(timestamp)

            # Cập nhật buffer confidence cho MỌI track đang thấy ở frame này,
            # bất kể có cắt line hay không — để khi cắt line ta có "trí nhớ"
            # vài frame gần nhất, không chỉ phụ thuộc đúng 1 frame trigger.
            for i in range(len(tracked)):
                if tracked.tracker_id is None:
                    continue
                tid = int(tracked.tracker_id[i])
                conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
                buf = recent_confidence.setdefault(tid, deque(maxlen=CONFIDENCE_WINDOW))
                buf.append(conf)

            for line in manual_lines:
                crossed_in_mask, crossed_out_mask = line.zone.trigger(detections=tracked)

                for i in range(len(tracked)):
                    if tracked.tracker_id is None:
                        continue
                    track_id = int(tracked.tracker_id[i])

                    # REVIEW FIX #4: dùng max confidence trong cửa sổ gần nhất
                    # thay vì confidence đúng frame trigger.
                    conf_buf = recent_confidence.get(track_id)
                    effective_confidence = max(conf_buf) if conf_buf else 0.0
                    if effective_confidence < COUNT_CONF_MIN:
                        continue

                    class_id = int(tracked.class_id[i])
                    class_name = VEHICLE_CLASSES.get(class_id, "unknown")

                    raw_direction: Optional[str] = None
                    if i < len(crossed_in_mask) and bool(crossed_in_mask[i]) and track_id not in line.counted_in_ids:
                        raw_direction = "in"
                    elif i < len(crossed_out_mask) and bool(crossed_out_mask[i]) and track_id not in line.counted_out_ids:
                        raw_direction = "out"

                    if raw_direction is None:
                        continue

                    # REVIEW FIX #2: đảo nhãn theo flip_direction nếu user xác
                    # nhận hướng vẽ bị ngược khi setup line.
                    direction = line.resolve_direction(raw_direction)

                    # REVIEW FIX #3: line 1 chiều — bỏ qua hướng không mong muốn.
                    if line.count_mode == "in_only" and direction != "in":
                        continue
                    if line.count_mode == "out_only" and direction != "out":
                        continue

                    if direction == "in":
                        line.counted_in_ids.add(track_id)
                    else:
                        line.counted_out_ids.add(track_id)

                    all_events.append({
                        "frame": frame_number,
                        "timestamp": round(timestamp, 3),
                        "track_id": track_id,
                        "class": class_name,
                        "confidence": round(effective_confidence, 4),
                        "direction": direction,
                        "line_id": line.id,
                        "line_label": line.label,
                    })
                    timeline_dict.setdefault(second, {
                        "second": second, "car": 0, "motorcycle": 0, "bus": 0, "truck": 0,
                    })
                    if class_name in timeline_dict[second]:
                        timeline_dict[second][class_name] += 1

            # ── Annotate frame ──
            annotated = frame.copy()
            annotated = trace_annotator.annotate(scene=annotated, detections=tracked)
            annotated = box_annotator.annotate(scene=annotated, detections=tracked)

            labels = []
            for i in range(len(tracked)):
                tid = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else -1
                cid = int(tracked.class_id[i])
                cname = VEHICLE_CLASSES.get(cid, "?")
                labels.append(f"#{tid} {cname}")
            if labels:
                annotated = label_annotator.annotate(scene=annotated, detections=tracked, labels=labels)

            for idx, line in enumerate(manual_lines):
                # Use ASCII-safe labels to avoid garbled text in OpenCV
                safe_label = f"Line {idx + 1}"
                count = line.total_count
                text = f"{safe_label}: {count}"
                
                # Draw custom label and line manually to ensure Unicode safety
                cv2.line(annotated, (line.start.x, line.start.y), (line.end.x, line.end.y), line_colors[idx % len(line_colors)], 3, cv2.LINE_AA)
                
                # Draw label box
                font = cv2.FONT_HERSHEY_SIMPLEX
                (tw, th), _ = cv2.getTextSize(text, font, 0.7, 2)
                tx = (line.start.x + line.end.x) // 2 - tw // 2
                ty = (line.start.y + line.end.y) // 2
                if idx % 2 == 0:
                    ty -= 10
                else:
                    ty += th + 10
                
                cv2.rectangle(annotated, (tx - 5, ty - th - 5), (tx + tw + 5, ty + 5), line_colors[idx % len(line_colors)], -1)
                cv2.putText(annotated, text, (tx, ty), font, 0.7, (0, 0, 0), 2, cv2.LINE_AA)

            writer.write(annotated)

            # ── Export live frames/stats for streaming ──
            if (frame_number + 1) % 5 == 0:  # Every 5 frames
                try:
                    cv2.imwrite(str(live_img_path), annotated)

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

                    if (frame_number + 1) % 15 == 0:
                        try:
                            with open(live_json_path, "w", encoding="utf-8") as f:
                                json.dump(live_results, f, ensure_ascii=False)
                        except Exception:
                            pass

                if callback and total_frames > 0:
                    progress = int((frame_number / total_frames) * 100)
                    callback(frame_number, total_frames, progress)

                if (frame_number + 1) % 15 == 0:
                    progress = int((frame_number / total_frames) * 100) if total_frames > 0 else 0
                    counts = ", ".join(f"{l.label}={l.total_count}" for l in manual_lines)
                    print(f"  ⏳ {progress}% — frame {frame_number + 1}/{total_frames} | {counts}")

    except Exception as e:
        print(f"[Process] Exception during processing: {e}")
        raise e
    finally:
        if 'writer' in locals() and writer:
            writer.release()
        # Cleanup live files
        try:
            live_json_path.unlink(missing_ok=True)
            live_img_path.unlink(missing_ok=True)
        except:
            pass
        counts = ", ".join(f"{l.label}={l.total_count}" for l in manual_lines)
        print(f"\n✅ [Manual] Xử lý xong! {len(all_events)} events | {counts}")

    # ── Build results JSON (giữ nguyên shape cũ để dashboard đọc được) ──
    timeline = []
    if timeline_dict:
        for sec in range(max(timeline_dict.keys()) + 1):
            timeline.append(timeline_dict.get(sec, {
                "second": sec, "car": 0, "motorcycle": 0, "bus": 0, "truck": 0,
            }))

    summary = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}
    for event in all_events:
        cls = event["class"]
        if cls in summary:
            summary[cls] += 1
    summary["total"] = sum(summary.values())

    results = {
        "metadata": {
            "video_duration": round(video_info["duration"], 3),
            "fps": round(fps, 3),
            "total_frames": total_frames,
            "resolution": video_info["resolution"],
            "processed_frames": frame_number + 1,
            "mode": "manual",
            "trigger_anchor": str(trigger_anchor),
            "lines": [ml.to_metadata() for ml in manual_lines],
        },
        "summary": summary,
        "timeline": timeline,
        "events": all_events,
    }

    import json
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[JSON] Saved to: {json_output_path}")
    print(f"[Video] Saved to: {output_path}")
    return results


# ──────────────────────────────────────────
# CLI entry point — test độc lập, không cần DB/API
# ──────────────────────────────────────────
if __name__ == "__main__":
    """
    Chạy thủ công qua command-line:
        python processing/process_manual.py <input> <output> <json> '<lines_json>'

    Ví dụ 1 line:
        python processing/process_manual.py uploads/test.mp4 outputs/out.mp4 outputs/result.json \
            '[{"id":"L1","label":"Line A","x1":0,"y1":540,"x2":1920,"y2":540}]'

    Ví dụ 2 line:
        python processing/process_manual.py uploads/test.mp4 outputs/out.mp4 outputs/result.json \
            '[{"id":"L1","label":"Vào","x1":0,"y1":400,"x2":960,"y2":400},
              {"id":"L2","label":"Ra","x1":960,"y1":700,"x2":1920,"y2":700}]'
    """
    import json as _json
    import supervision as _sv

    if len(sys.argv) < 5:
        print("Usage: python processing/process_manual.py <input> <output> <json> '<lines_json>' [--anchor BOTTOM_CENTER]")
        sys.exit(1)

    input_video, output_video, output_json, lines_json = sys.argv[1:5]

    # Parse optional --anchor argument
    anchor_str = DEFAULT_TRIGGER_ANCHOR.name
    if "--anchor" in sys.argv:
        idx = sys.argv.index("--anchor")
        if idx + 1 < len(sys.argv):
            anchor_str = sys.argv[idx + 1]

    try:
        anchor = _sv.Position[anchor_str]
        parsed_lines = _json.loads(lines_json)
        print(f"🚗 Vehicle Counting — Manual Line Mode | {len(parsed_lines)} line(s), anchor={anchor_str}")
        results = process_video_file_manual(input_video, output_video, output_json, parsed_lines, trigger_anchor=anchor)
        print(f"\n✅ Done! Summary: {results['summary']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
