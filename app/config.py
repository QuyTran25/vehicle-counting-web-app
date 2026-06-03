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

MODEL_NAME = "yolov8n.pt"
CONF_THRESHOLD = 0.35  # Confidence threshold for YOLO detection
IOU_THRESHOLD = 0.45   # IoU threshold for NMS

# Video Processing Configuration
MAX_VIDEO_SIZE_MB = 500  # Maximum allowed upload size
SUPPORTED_VIDEO_FORMATS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

# ByteTrack Configuration

TRACK_ACTIVATIONS = 30   # Frames to keep inactive track alive
TRACK_MAX_AGE = 30       # Maximum frames to keep a track


# LineZone Configuration (For future use - Week 4)
# These are default values - will be customizable per video
LINE_START = (0, 540)      # Default: horizontal line at y=540
LINE_END = (1920, 540)     # Default: for 1920x1080 resolution

# Output Video Configuration
OUTPUT_VIDEO_CODEC = "mp4v"  # or "h264" for compatibility
OUTPUT_VIDEO_FPS = 30        # Keep same FPS as input
OUTPUT_VIDEO_QUALITY = 85    # JPEG quality for encoding

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
