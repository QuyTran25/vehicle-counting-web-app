import os
from pathlib import Path

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

# YOLO & Detection Configuration

# yolov8s.pt tốt hơn yolov8n.pt cho xe nhỏ/xa, chấp nhận chậm hơn ~20%
MODEL_NAME = "yolov8s.pt"
CONF_THRESHOLD = 0.25  # Thấp để bắt xe máy nhỏ/xa; confidence filter khi đếm dùng COUNT_CONF_MIN
IOU_THRESHOLD = 0.45   # IoU threshold for NMS

# Chỉ đếm crossing khi confidence đủ cao (tránh false positive)
COUNT_CONF_MIN = 0.45

# Video Processing Configuration
MAX_VIDEO_SIZE_MB = 500  # Maximum allowed upload size
SUPPORTED_VIDEO_FORMATS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

# ByteTrack Configuration
# frame_rate sẽ được truyền động từ fps thực của video trong process.py
TRACK_LOST_BUFFER = 60        # giữ track 60 frames khi mất detection (~3s ở 20fps)
TRACK_ACTIVATION_THRESHOLD = 0.25
TRACK_MINIMUM_MATCHING = 0.7
TRACK_MINIMUM_CONSECUTIVE = 1  # kích hoạt track ngay frame đầu để không miss xe máy

# LineZone Configuration
LINE_START = (0, 540)
LINE_END = (1920, 540)
LINE_AUTO_Y_RATIO = 0.72   # 72% chiều cao → xe lớn hơn, tracking ổn định hơn khi qua line

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