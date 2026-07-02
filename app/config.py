import os
from pathlib import Path
import supervision as sv

# Project Paths

PROJECT_ROOT = Path(__file__).parent.parent
UPLOADS_DIR = PROJECT_ROOT / "uploads"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
MODELS_DIR = PROJECT_ROOT / "models"
DB_PATH = PROJECT_ROOT / "database.db"


# Create directories if not exist
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Vehicle Classes (YOLO COCO Dataset)
VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}
CLASS_IDS = list(VEHICLE_CLASSES.keys())  # [2, 3, 5, 7]

# Video Processing Configuration
MAX_VIDEO_SIZE_MB = 500  # Maximum allowed upload size
SUPPORTED_VIDEO_FORMATS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

# ─────────────────────────────────────────────────────────────────────────────
# DETECTION CONFIGURATION - Tối ưu cho độ chính xác cao
# ─────────────────────────────────────────────────────────────────────────────

# Model: yolov8s.pt — pretrained Ultralytics model (balanced speed/accuracy)
# Available models: yolov8n.pt (nano), yolov8s.pt (small), yolov8m.pt (medium), yolov8l.pt (large)
MODEL_NAME = "yolov8s.pt"

# Confidence thresholds - TĂNG để giảm false positive
CONF_THRESHOLD = 0.35       # Chỉ detect khi model chắc chắn ≥35%
COUNT_CONF_MIN = 0.40       # Chỉ đếm khi confidence ≥40% (cao hơn detect)

# NMS IoU - GIẢM để giữ lại nhiều detections hơn
IOU_THRESHOLD = 0.50         # Giảm từ 0.65 - tránh miss overlapping vehicles

# ─────────────────────────────────────────────────────────────────────────────
# SIZE FILTERING - Loại bỏ false detections quá nhỏ/lớn
# ─────────────────────────────────────────────────────────────────────────────

MIN_BOX_AREA = 400           # Diện tích tối thiểu (pixels²) - loại noise
MAX_BOX_AREA = 500000         # Diện tích tối đa - loại bỏ anomalies
MIN_BOX_WIDTH = 20            # Chiều rộng tối thiểu
MIN_BOX_HEIGHT = 20           # Chiều cao tối thiểu
MAX_ASPECT_RATIO = 8.0        # Tỷ lệ width/height tối đa (xe không quá dài)
MIN_ASPECT_RATIO = 0.15       # Tỷ lệ tối thiểu (xe không quá cao)

# ─────────────────────────────────────────────────────────────────────────────
# TEMPORAL SMOOTHING - Yêu cầu detection phải xuất hiện nhiều frames
# ─────────────────────────────────────────────────────────────────────────────

TEMPORAL_CONFIRM_FRAMES = 2   # Detect cần xuất hiện 2 frames liên tiếp
                                # Giúp loại bỏ flickers và ghost detections

# ─────────────────────────────────────────────────────────────────────────────
# BYTETRACK CONFIG - Tracking ổn định hơn
# ─────────────────────────────────────────────────────────────────────────────

# frame_rate sẽ được truyền động từ fps thực của video trong process.py
TRACK_LOST_BUFFER = 45         # Giảm từ 60 - tránh phantom tracks (2s @ 22fps)
TRACK_ACTIVATION_THRESHOLD = 0.30  # Tăng nhẹ - yêu cầu detection rõ hơn
TRACK_MINIMUM_MATCHING = 0.80  # Tăng từ 0.7 - matching strict hơn
TRACK_MINIMUM_CONSECUTIVE = 2  # Tăng từ 1 - cần 2 frames liên tiếp mới activate

# LineZone Configuration
LINE_ANCHOR = sv.Position.CENTER  # Sử dụng tâm hình học thay vì BOTTOM_CENTER để ổn định
LINE_START = (0, 540)
LINE_END = (1920, 540)
LINE_AUTO_Y_RATIO = 0.72   # 72% chiều cao → xe lớn hơn, tracking ổn định hơn khi qua line

# Làn đường đơn / đôi:
# - True: chỉ có 1 làn (1 LineZone duy nhất ở giữa)
# - False: có 2 làn (Left = OUT, Right = IN)
# Lưu ý: Tự động cho dashboard để user cấu hình là phiên bản tương lai.
IS_SINGLE_LANE = False  # Mặc định là 2 làn

# Output Video Configuration
OUTPUT_VIDEO_CODEC = "avc1"  # Try H.264 container-friendly codec for better output quality
OUTPUT_VIDEO_FPS = 30        # Keep same FPS as input when possible
OUTPUT_VIDEO_QUALITY = 95    # Higher quality hint for VideoWriter

# Database Configuration
DB_CONFIG = {
    "path": str(DB_PATH),
    "timeout": 30,
}

# Task & Processing Configuration

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_PROCESSING = "processing"
TASK_STATUS_DONE = "done"
TASK_STATUS_FAILED = "failed"

TASK_STATUSES = [
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
]