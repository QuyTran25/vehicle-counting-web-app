"""
Core video processing engine: YOLO Detection + ByteTrack
"""
import json
import sys
from pathlib import Path
from typing import Generator, Dict, List, Any

import cv2
import supervision as sv
from ultralytics import YOLO

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import (
    MODEL_NAME, 
    CONF_THRESHOLD, 
    IOU_THRESHOLD,
    CLASS_IDS,
    VEHICLE_CLASSES,
    MODELS_DIR,
)
from processing.utils import (
    validate_video,
    get_video_info,
    video_frame_generator,
    create_video_writer,
)


class VehicleDetector:
    """
    Main vehicle detection engine combining YOLO + ByteTrack
    """
    
    def __init__(self):
        """Initialize YOLO model and ByteTrack tracker"""
        self.model = None
        self.tracker = None
        self._init_model()
        self._init_tracker()
    
    def _init_model(self):
        """Load YOLO model"""
        model_path = MODELS_DIR / MODEL_NAME
        
        if not model_path.exists():
            print(f"📥 Downloading {MODEL_NAME}...")
            self.model = YOLO(MODEL_NAME)
            print("✅ Model loaded successfully!")
        else:
            print(f"📂 Loading {MODEL_NAME} from local...")
            self.model = YOLO(str(model_path))
            print("✅ Model loaded successfully!")
    
    def _init_tracker(self):
        """Initialize ByteTrack tracker with tuned parameters for stable tracking"""
        self.tracker = sv.ByteTrack(
            lost_track_buffer=50,              # keep track alive for 50 frames when detection is lost
            track_activation_threshold=0.25,   # default threshold for track activation
            minimum_matching_threshold=0.7,    # stricter matching = fewer false ID switches
            frame_rate=30,
        )
    
    def detect_frame(self, frame) -> sv.Detections:
        """
        Detect vehicles in a single frame using YOLO.
        
        Args:
            frame: Input frame (numpy array)
            
        Returns:
            sv.Detections: Detection results from supervision
        """
        # Run YOLO inference
        results = self.model(
            frame,
            conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD,
            classes=CLASS_IDS,
            verbose=False,
        )
        
        # Convert to supervision format
        detections = sv.Detections.from_ultralytics(results[0])
        return detections
    
    def update_tracker(self, detections: sv.Detections) -> sv.Detections:
        """
        Update ByteTrack with detections and return tracked detections.
        
        Args:
            detections: YOLO detections
            
        Returns:
            sv.Detections: Detections with track_id assigned
        """
        detections = self.tracker.update_with_detections(detections)
        return detections
    
    def process_video(
        self,
        input_path: str,
        output_path: str,
        json_output_path: str,
        callback=None,
    ) -> Dict[str, Any]:
        """
        Process video frame-by-frame with detection and tracking.
        
        Args:
            input_path: Path to input video
            output_path: Path to save output video with annotations
            json_output_path: Path to save detection data as JSON
            callback: Optional callback function to report progress
                     Called with (frame_num, total_frames, detections_data)
        
        Returns:
            dict: Processing results including metadata and detection summary
        """
        
        # Validate video
        is_valid, error_msg = validate_video(input_path)
        if not is_valid:
            raise ValueError(f"Invalid video: {error_msg}")
        
        # Get video info
        video_info = get_video_info(input_path)
        print(f"\n📹 Video Info: {video_info['resolution']} @ {video_info['fps']:.1f}fps, {video_info['duration']:.1f}s")
        
        # Initialize video writer
        writer = create_video_writer(
            output_path,
            video_info["fps"],
            video_info["width"],
            video_info["height"],
        )
        
        # Tracking data
        frame_number = 0
        total_frames = video_info["frame_count"]
        all_events = []
        timeline_dict = {}  # second -> detection counts
        
        # Setup annotation drawer
        box_annotator = sv.BoundingBoxAnnotator()
        label_annotator = sv.LabelAnnotator()
        trace_annotator = sv.TraceAnnotator(
            trace_length=50,                    # 50 most recent positions
            thickness=2,
            color_lookup=sv.ColorLookup.TRACK,  # unique color per track_id
        )
        
        try:
            # Process each frame
            for frame_number, frame in video_frame_generator(input_path):
                # Detect vehicles
                detections = self.detect_frame(frame)
                
                # Update tracking
                tracked_detections = self.update_tracker(detections)
                
                # Prepare frame data for JSON
                frame_data = self._prepare_frame_data(
                    frame_number,
                    video_info["fps"],
                    tracked_detections,
                )
                
                # Record events and timeline
                for detection in frame_data["detections"]:
                    all_events.append({
                        "frame": frame_number,
                        "timestamp": frame_number / video_info["fps"],
                        "track_id": detection["track_id"],
                        "class": detection["class"],
                        "confidence": detection["confidence"],
                    })
                
                # Update timeline (unique track_ids per second)
                second = int(frame_number / video_info["fps"])
                if second not in timeline_dict:
                    timeline_dict[second] = {
                        "second": second,
                        "car": 0,
                        "motorcycle": 0,
                        "bus": 0,
                        "truck": 0,
                        "_seen_ids": set(),  # track unique IDs in this second
                    }

                for detection in frame_data["detections"]:
                    tid = detection["track_id"]
                    cls = detection["class"]
                    if tid not in timeline_dict[second]["_seen_ids"]:
                        timeline_dict[second]["_seen_ids"].add(tid)
                        if cls in ("car", "motorcycle", "bus", "truck"):
                            timeline_dict[second][cls] += 1
                
                # Annotate frame (box + label + trace)
                annotated_frame = self._annotate_frame(
                    frame,
                    tracked_detections,
                    box_annotator,
                    label_annotator,
                    trace_annotator,
                )
                
                # Write frame to output video
                writer.write(annotated_frame)
                
                # Progress callback
                if callback:
                    progress = int((frame_number / total_frames) * 100)
                    callback(frame_number, total_frames, progress)
                
                # Progress logging (every 30 frames)
                if (frame_number + 1) % 30 == 0:
                    progress = int((frame_number / total_frames) * 100)
                    print(f"  Processing: {progress}% ({frame_number}/{total_frames} frames)")
        
        finally:
            writer.release()
            print("✅ Video processing complete!")
        
        # Prepare results JSON (remove internal _seen_ids set)
        timeline = []
        for sec in sorted(timeline_dict.keys()):
            entry = {k: v for k, v in timeline_dict[sec].items() if k != "_seen_ids"}
            timeline.append(entry)
        
        results = {
            "metadata": {
                "video_duration": video_info["duration"],
                "fps": video_info["fps"],
                "total_frames": video_info["frame_count"],
                "resolution": video_info["resolution"],
                "processed_frames": frame_number + 1,
            },
            "summary": self._compute_summary(all_events),
            "timeline": timeline,
            "events": all_events,
        }
        
        # Save results to JSON
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Results saved to: {json_output_path}")
        return results
    
    def _prepare_frame_data(self, frame_number: int, fps: float, detections: sv.Detections) -> dict:
        """
        Prepare detection data for a single frame.
        
        Args:
            frame_number: Frame index
            fps: Video FPS
            detections: Supervision detections
            
        Returns:
            dict: Frame data with detections
        """
        timestamp = frame_number / fps
        
        detections_list = []
        for i in range(len(detections)):
            class_id = detections.class_id[i]
            confidence = detections.confidence[i] if detections.confidence is not None else 0.0
            track_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else -1
            
            class_name = VEHICLE_CLASSES.get(int(class_id), "unknown")
            
            # Get bounding box coordinates (xyxy format: x1, y1, x2, y2)
            x1, y1, x2, y2 = detections.xyxy[i]
            detections_list.append({
                "track_id": track_id,
                "class": class_name,
                "confidence": float(confidence),
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
            })
        
        return {
            "frame": frame_number,
            "timestamp": timestamp,
            "detections": detections_list,
        }
    
    def _annotate_frame(self, frame, detections: sv.Detections,
                        box_annotator, label_annotator, trace_annotator) -> cv2.Mat:
        """
        Draw bounding boxes, labels, and tracking trails on frame.

        Args:
            frame: Input frame
            detections: Detected vehicles with tracking info
            box_annotator: Supervision box annotator
            label_annotator: Supervision label annotator
            trace_annotator: Supervision trace annotator (draws movement path)

        Returns:
            cv2.Mat: Annotated frame
        """
        annotated_frame = frame.copy()

        # 1. Draw tracking trails (BEFORE boxes so boxes are on top)
        annotated_frame = trace_annotator.annotate(
            scene=annotated_frame,
            detections=detections,
        )

        # 2. Draw bounding boxes
        annotated_frame = box_annotator.annotate(
            scene=annotated_frame,
            detections=detections,
        )

        # 3. Prepare labels (Track ID + Class + Confidence)
        labels = []
        for i in range(len(detections)):
            track_id = int(detections.tracker_id[i]) if detections.tracker_id is not None else -1
            class_id = int(detections.class_id[i])
            class_name = VEHICLE_CLASSES.get(class_id, "unknown")
            confidence = detections.confidence[i] if detections.confidence is not None else 0.0

            label = f"#{track_id} {class_name} {confidence:.2f}"
            labels.append(label)

        # 4. Draw labels
        if labels:
            annotated_frame = label_annotator.annotate(
                scene=annotated_frame,
                detections=detections,
                labels=labels,
            )

        return annotated_frame
    
    def _compute_summary(self, events: List[dict]) -> dict:
        """
        Compute summary: count UNIQUE vehicles by track_id.

        Args:
            events: List of all detection events

        Returns:
            dict: Unique vehicle counts per class, plus total
        """
        # Track unique vehicles: track_id -> class_name
        unique_vehicles = {}
        for event in events:
            tid = event["track_id"]
            if tid not in unique_vehicles:
                unique_vehicles[tid] = event["class"]

        summary = {
            "car": 0,
            "motorcycle": 0,
            "bus": 0,
            "truck": 0,
        }

        for class_name in unique_vehicles.values():
            if class_name in summary:
                summary[class_name] += 1

        summary["total"] = sum(summary.values())
        return summary


def process_video_file(input_path: str, output_path: str, json_output_path: str, callback=None) -> Dict:
    """
    Standalone function to process a video file.
    
    Args:
        input_path: Path to input video
        output_path: Path to save annotated video
        json_output_path: Path to save JSON results
        callback: Optional progress callback
        
    Returns:
        dict: Processing results
    """
    detector = VehicleDetector()
    results = detector.process_video(input_path, output_path, json_output_path, callback)
    return results


if __name__ == "__main__":
    # Test with command line arguments
    if len(sys.argv) < 4:
        print("Usage: python process.py <input_video> <output_video> <output_json>")
        sys.exit(1)
    
    input_video = sys.argv[1]
    output_video = sys.argv[2]
    output_json = sys.argv[3]
    
    try:
        results = process_video_file(input_video, output_video, output_json)
        print(f"\n✅ Processing complete!")
        print(f"Summary: {results['summary']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
