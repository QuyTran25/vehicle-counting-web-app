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

# Model: best.pt — custom model trained for Vietnam traffic
# yolov8s/yolov8m/yolov8l = pretrained Ultralytics models
MODEL_NAME = "best.pt"

# Confidence thresholds - GIẢM để bắt được nhiều xe hơn (đặc biệt xe ở xa hoặc bị che một phần)
CONF_THRESHOLD = 0.20       # Giảm từ 0.35 xuống 0.20
COUNT_CONF_MIN = 0.25       # Giảm từ 0.40 xuống 0.25

# NMS IoU - TĂNG để giữ lại nhiều detections hơn (cực kỳ quan trọng ở VN vì xe máy đi rất sát nhau, hay bị đè box)
IOU_THRESHOLD = 0.70         # Tăng từ 0.50 lên 0.70 để không bị xóa nhầm xe đứng cạnh nhau

# ─────────────────────────────────────────────────────────────────────────────
# SIZE FILTERING - Loại bỏ false detections quá nhỏ/lớn
# ─────────────────────────────────────────────────────────────────────────────

MIN_BOX_AREA = 100           # Giảm từ 400 xuống 100 để không bỏ sót xe máy ở xa
MAX_BOX_AREA = 500000         # Diện tích tối đa - loại bỏ anomalies
MIN_BOX_WIDTH = 10            # Chiều rộng tối thiểu
MIN_BOX_HEIGHT = 10           # Chiều cao tối thiểu
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
TRACK_LOST_BUFFER = 90         # Tăng lên 90 frames (khoảng 3s) để giữ ID khi xe lọt vào điểm mù hoặc bị xe tải che khuất
TRACK_ACTIVATION_THRESHOLD = 0.20  # Giảm xuống 0.20 để dễ dàng bắt đầu theo dõi
TRACK_MINIMUM_MATCHING = 0.50  # Giảm từ 0.8 xuống 0.5 để dễ khớp ID hơn khi xe chuyển làn gắt hoặc lạng lách
TRACK_MINIMUM_CONSECUTIVE = 1  # Chỉ cần 1 frame là bắt đầu activate

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