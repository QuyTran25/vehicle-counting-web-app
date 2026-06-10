"""
Utility functions for video processing
"""
import cv2
from pathlib import Path
from typing import Tuple, Optional
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import SUPPORTED_VIDEO_FORMATS, MAX_VIDEO_SIZE_MB


def validate_video(video_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if a video file is readable and has supported format.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    try:
        # Check if file exists
        path = Path(video_path)
        if not path.exists():
            return False, f"Video file not found: {video_path}"
        
        # Check file extension
        if path.suffix.lower() not in SUPPORTED_VIDEO_FORMATS:
            supported = ", ".join(SUPPORTED_VIDEO_FORMATS)
            return False, f"Unsupported format. Supported: {supported}"
        
        # Check file size
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_VIDEO_SIZE_MB:
            return False, f"Video too large. Max: {MAX_VIDEO_SIZE_MB}MB, Got: {file_size_mb:.1f}MB"
        
        # Try to open with OpenCV
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False, "Cannot open video file. File may be corrupted or codec not supported."
        
        # Check if video has frames
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count == 0:
            cap.release()
            return False, "Video has no frames"
        
        cap.release()
        return True, None
        
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def get_video_info(video_path: str) -> dict:
    """
    Extract video metadata.
    
    Args:
        video_path: Path to video file
        
    Returns:
        dict: Video metadata including duration, fps, resolution, frame_count
    """
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Handle edge case where FPS might be 0
        if fps == 0:
            fps = 30  # Default fallback
        
        duration = frame_count / fps if fps > 0 else 0
        
        return {
            "frame_count": frame_count,
            "fps": fps,
            "width": width,
            "height": height,
            "duration": duration,
            "resolution": f"{width}x{height}",
        }
    finally:
        cap.release()


def video_frame_generator(video_path: str):
    """
    Generator that yields frames from video file.
    
    Args:
        video_path: Path to video file
        
    Yields:
        Tuple[int, ndarray]: (frame_number, frame_data)
    """
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    
    frame_number = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            yield frame_number, frame
            frame_number += 1
    finally:
        cap.release()


def create_video_writer(output_path: str, fps: float, width: int, height: int, 
                       codec: str = "mp4v") -> cv2.VideoWriter:
    """
    Create OpenCV VideoWriter for output.
    
    Args:
        output_path: Path to output video file
        fps: Frames per second
        width: Frame width
        height: Frame height
        codec: Video codec (e.g., 'mp4v', 'MJPG', 'XVID')
        
    Returns:
        cv2.VideoWriter: Video writer object
    """
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    if not writer.isOpened():
        raise RuntimeError(f"Failed to create VideoWriter with codec '{codec}'")
    
    return writer


def verify_codec(video_path: str) -> Tuple[bool, Optional[str]]:
    """
    Kiểm tra xem video output có mở được trên trình duyệt (Chrome, Firefox) 
    và media player (VLC) không.
    
    Yêu cầu: ffprobe (từ FFmpeg)
    
    Args:
        video_path: Đường dẫn file video output
        
    Returns:
        Tuple[bool, Optional[str]]: (is_playable, error_message)
    """
    import subprocess
    
    try:
        # Kiểm tra file tồn tại
        path = Path(video_path)
        if not path.exists():
            return False, f"File not found: {video_path}"
        
        # Kiểm tra codec bằng ffprobe
        # Nếu không có ffprobe, dùng cv2 để kiểm tra tối thiểu
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", str(video_path)],
                capture_output=True,
                timeout=10,
                text=True,
            )
            if result.returncode != 0:
                return False, f"FFprobe error: {result.stderr[:200]}"
            
            # Kiểm tra codec trong output
            if "h264" not in result.stdout and "avc1" not in result.stdout and "mp4v" not in result.stdout:
                # Cảnh báo nhưng không thất bại (có codec khác có thể chạy)
                return True, "Warning: Non-H.264/H.265 codec detected, may have compatibility issues"
            
            return True, None
            
        except FileNotFoundError:
            # ffprobe không tìm thấy, dùng cv2 để kiểm tra cơ bản
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return False, "Cannot open video with cv2.VideoCapture"
            cap.release()
            return True, "Playable (OpenCV check passed)"
            
    except Exception as e:
        return False, f"Verification error: {str(e)}"
