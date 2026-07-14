"""
FastAPI backend for vehicle detection web application
"""
import uuid
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel

class ManualLinesRequest(BaseModel):
    lines: List[dict]
    trigger_anchor: str = "BOTTOM_CENTER"

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles
import asyncio

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import (
    UPLOADS_DIR,
    OUTPUTS_DIR,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
    SUPPORTED_VIDEO_FORMATS,
    MAX_VIDEO_SIZE_MB,
)
from app.database import Database, get_connection
from processing.utils import validate_video


# Initialize FastAPI app
app = FastAPI(
    title="Vehicle Detection API",
    description="Real-time vehicle detection and tracking",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
db = Database()

# Startup Cleanup Event
@app.on_event("startup")
async def startup_event():
    """Reset stuck tasks to failed state on startup"""
    try:
        conn = get_connection()
        conn.execute(
            """UPDATE tasks
               SET status = 'failed', error_msg = 'Server restarted or crashed during processing', progress = 0
               WHERE status IN ('queued', 'processing')"""
        )
        conn.commit()
        conn.close()
        print("[DB] Reset stuck tasks on startup successfully.")
    except Exception as e:
        print(f"[DB] Error resetting stuck tasks on startup: {str(e)}")

# Static files
try:
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")
except:
    print("[Static] Static files directory not found, skipping mount")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Serve dashboard page"""
    try:
        template_path = Path(__file__).parent.parent / "templates" / "dashboard.html"
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        return {
            "message": "Vehicle Detection API - Dashboard",
            "version": "1.0.0",
            "error": f"Could not load dashboard template: {str(e)}",
            "endpoints": {
                "upload": "POST /upload",
                "status": "GET /status/{task_id}",
                "result": "GET /result/{task_id}",
                "tasks": "GET /tasks",
            }
        }


@app.get("/history")
async def history():
    """Serve history page"""
    try:
        template_path = Path(__file__).parent.parent / "templates" / "history.html"
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        return {
            "message": "Vehicle Detection API - History",
            "version": "1.0.0",
            "error": f"Could not load history template: {str(e)}"
        }


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), single_lane: bool = Form(False), mode: str = Form("auto")):
    """
    Upload video for processing
    
    Args:
        file: Video file
        single_lane: True = 1 làn (auto mode), False = 2 làn (auto mode)
        mode: "auto" | "manual"
    
    Returns:
        task_id: Unique identifier for this processing task
        status: queued
    """
    try:
        # Validate mode
        if mode not in ("auto", "manual"):
            raise HTTPException(
                status_code=400,
                detail=f"Mode không hợp lệ: {mode}. Chỉ hỗ trợ 'auto' hoặc 'manual'"
            )
        
        # Validate file extension
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in SUPPORTED_VIDEO_FORMATS:
            supported = ", ".join(SUPPORTED_VIDEO_FORMATS)
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format. Supported: {supported}"
            )
        
        # Create task ID
        task_id = str(uuid.uuid4())
        
        # Save uploaded file
        file_path = UPLOADS_DIR / f"{task_id}{file_ext}"
        
        async with aiofiles.open(str(file_path), "wb") as f:
            content = await file.read()
            
            # Check file size
            file_size_mb = len(content) / (1024 * 1024)
            if file_size_mb > MAX_VIDEO_SIZE_MB:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Max: {MAX_VIDEO_SIZE_MB}MB"
                )
            
            await f.write(content)
        
        # Validate video
        is_valid, error_msg = validate_video(str(file_path))
        if not is_valid:
            file_path.unlink()  # Delete invalid file
            raise HTTPException(status_code=400, detail=f"Invalid video: {error_msg}")
        
        # Create task in database
        db.create_task(task_id, file.filename)
        
        if mode == "manual":
            # Manual mode: don't auto-process, just upload
            # User will draw lines and trigger processing later
            return {
                "task_id": task_id,
                "status": "uploaded",
                "mode": "manual",
                "message": "Video uploaded. Please draw counting lines and click process.",
                "filename": file.filename,
            }
        else:
            # Auto mode: start processing immediately
            from app.process_runner import run_process_in_background
            run_process_in_background(task_id, str(file_path), single_lane=single_lane)
            
            return {
                "task_id": task_id,
                "status": TASK_STATUS_QUEUED,
                "mode": "auto",
                "message": "Video uploaded successfully. Processing started.",
                "filename": file.filename,
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """
    Get current processing status
    
    Returns:
        status: queued / processing / done / failed
        progress: 0-100 (%)
        error_msg: Error message if failed
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        response = {
            "task_id": task_id,
            "status": task["status"],
            "progress": task["progress"],
            "error_msg": task.get("error_msg"),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }
        
        # Load realtime stats if available
        if task["status"] == TASK_STATUS_PROCESSING:
            live_json_path = OUTPUTS_DIR / f"{task_id}_live.json"
            if live_json_path.exists():
                try:
                    with open(live_json_path, "r", encoding="utf-8") as f:
                        response["live_stats"] = json.load(f)
                except Exception:
                    pass
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stream/{task_id}")
async def stream_video(task_id: str):
    """Stream MJPEG frames for real-time visualization"""
    live_path = OUTPUTS_DIR / f"{task_id}_live.jpg"
    
    async def frame_generator():
        last_mtime = 0
        while True:
            task = db.get_task(task_id)
            if not task or task["status"] in [TASK_STATUS_DONE, TASK_STATUS_FAILED]:
                break
            if live_path.exists():
                try:
                    mtime = live_path.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        with open(live_path, "rb") as f:
                            frame = f.read()
                        if frame:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                except Exception:
                    pass
            await asyncio.sleep(0.05) # ~20 FPS polling
            
    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/result/{task_id}")
async def get_result(task_id: str):
    """
    Get processing result (JSON data)
    
    Returns:
        metadata: Video info
        summary: Total counts per vehicle class
        timeline: Counts per second
        events: All detection events
        output_video: Path to annotated video
        output_json: Path to JSON results
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task["status"] != TASK_STATUS_DONE:
            raise HTTPException(
                status_code=400,
                detail=f"Task not completed yet. Current status: {task['status']}"
            )
        
        # Load JSON results
        json_path = OUTPUTS_DIR / f"{task_id}_result.json"
        if not json_path.exists():
            raise HTTPException(status_code=500, detail="Result file not found")
        
        with open(json_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        
        # Translate 'motorcycle' to 'motorbike' to match JSON schema contract
        if "summary" in results:
            summary = results["summary"]
            if "motorcycle" in summary:
                summary["motorbike"] = summary.pop("motorcycle")
        
        if "timeline" in results and isinstance(results["timeline"], list):
            for item in results["timeline"]:
                if "motorcycle" in item:
                    item["motorbike"] = item.pop("motorcycle")
                    
        if "events" in results and isinstance(results["events"], list):
            for evt in results["events"]:
                if evt.get("class") == "motorcycle":
                    evt["class"] = "motorbike"

        # Add file paths
        results["output_video"] = f"/output/{task_id}_output.mp4"
        results["output_json"] = f"/output/{task_id}_result.json"
        
        return results
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks")
async def list_tasks(limit: int = 20, offset: int = 0):
    """
    Get list of all tasks
    
    Query params:
        limit: Maximum number of tasks to return (default: 20)
        offset: Pagination offset (default: 0)
    """
    try:
        tasks = db.list_tasks(limit=limit, offset=offset)
        return {
            "count": len(tasks),
            "limit": limit,
            "offset": offset,
            "tasks": tasks,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/output/{filename}")
async def download_output(filename: str):
    """
    Download output file (video or JSON)
    """
    try:
        file_path = OUTPUTS_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """
    Delete a task and its associated files
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Delete files
        input_pattern = str(UPLOADS_DIR / f"{task_id}*")
        output_pattern = str(OUTPUTS_DIR / f"{task_id}*")
        
        import glob
        for file in glob.glob(input_pattern):
            Path(file).unlink(missing_ok=True)
        for file in glob.glob(output_pattern):
            Path(file).unlink(missing_ok=True)
        
        # Delete from database
        db.delete_task(task_id)
        
        return {"message": "Task deleted successfully", "task_id": task_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Manual Line Config Endpoints
# ============================================================================

@app.get("/tasks/{task_id}/first-frame")
async def get_first_frame(task_id: str):
    """
    Lấy frame đầu tiên của video để vẽ line thủ công.
    Trả về ảnh JPEG.
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Tìm file video đã upload
        import glob
        input_pattern = str(UPLOADS_DIR / f"{task_id}*")
        video_files = glob.glob(input_pattern)
        
        if not video_files:
            raise HTTPException(status_code=404, detail="Video file not found")

        video_path = video_files[0]

        # Đọc frame đầu bằng OpenCV
        import cv2
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            raise HTTPException(status_code=500, detail="Cannot read video frame")

        # Encode thành JPEG
        import numpy as np
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        _, img_encoded = cv2.imencode('.jpg', frame, encode_param)
        
        return StreamingResponse(
            iter([img_encoded.tobytes()]),
            media_type="image/jpeg",
            headers={
                "X-Video-Width": str(frame.shape[1]),
                "X-Video-Height": str(frame.shape[0]),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/tasks/{task_id}/manual-lines")
async def save_manual_lines(task_id: str, request: ManualLinesRequest):
    """
    Lưu line config thủ công cho task.
    
    lines: Danh sách 1-2 line, mỗi phần tử dạng:
        {
            "id": "L1",
            "label": "Line A",
            "x1": 0, "y1": 540, "x2": 1920, "y2": 540,
            "flip_direction": false,
            "count_mode": "both"  # "both" | "in_only" | "out_only"
        }
    trigger_anchor: "BOTTOM_CENTER" | "CENTER" | "TOP_CENTER"
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        lines = request.lines
        trigger_anchor = request.trigger_anchor

        if not lines:
            raise HTTPException(status_code=400, detail="Cần ít nhất 1 line để xử lý thủ công")

        if len(lines) > 2:
            raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tối đa 2 line")

        # Validate trigger_anchor
        valid_anchors = {"BOTTOM_CENTER", "CENTER", "TOP_CENTER"}
        if trigger_anchor not in valid_anchors:
            raise HTTPException(status_code=400, detail=f"trigger_anchor phải thuộc {valid_anchors}")

        # Lưu vào DB
        db.save_line_config(task_id, lines, trigger_anchor)

        return {
            "message": "Line config saved successfully",
            "task_id": task_id,
            "lines_count": len(lines),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}/manual-lines")
async def get_manual_lines(task_id: str):
    """Lấy line config đã lưu của task."""
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        config = db.get_line_config(task_id)
        if not config:
            return {"lines": [], "trigger_anchor": None}

        return config

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/tasks/{task_id}/manual-lines")
async def delete_manual_lines(task_id: str):
    """Xóa line config của task."""
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        db.delete_line_config(task_id)
        return {"message": "Line config deleted", "task_id": task_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tasks/{task_id}/process")
async def trigger_process(task_id: str):
    """
    Kích hoạt xử lý video (dùng cho manual mode sau khi vẽ line xong).
    Kiểm tra line_config đã có, nếu chưa có thì báo lỗi.
    """
    try:
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if task["status"] in (TASK_STATUS_PROCESSING, TASK_STATUS_DONE):
            raise HTTPException(
                status_code=400,
                detail=f"Task đã ở trạng thái {task['status']}. Không thể xử lý lại."
            )

        # Kiểm tra line config cho manual mode
        line_config = db.get_line_config(task_id)
        if not line_config:
            raise HTTPException(
                status_code=400,
                detail="Bạn cần vẽ line trước khi xử lý. Hãy vẽ ít nhất 1 line."
            )

        # Tìm file video
        import glob
        input_pattern = str(UPLOADS_DIR / f"{task_id}*")
        video_files = glob.glob(input_pattern)

        if not video_files:
            raise HTTPException(status_code=404, detail="Video file not found")

        video_path = video_files[0]

        # Xử lý ngay
        from app.process_runner import run_process_in_background
        run_process_in_background(task_id, video_path, single_lane=False)

        return {
            "task_id": task_id,
            "status": TASK_STATUS_QUEUED,
            "mode": "manual",
            "message": "Processing started with your custom lines.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Background Processing
# ============================================================================

def process_video_task(task_id: str, video_path: str):
    """
    Background task to process video.
    Tự động phân biệt Auto vs Manual mode dựa trên line_config.
    """
    try:
        # Update status to processing
        db.update_task_status(task_id, TASK_STATUS_PROCESSING, progress=0)
        
        # Prepare output paths
        output_video = OUTPUTS_DIR / f"{task_id}_output.mp4"
        output_json = OUTPUTS_DIR / f"{task_id}_result.json"

        def progress_callback(frame_num, total_frames, progress):
            """Update progress in database"""
            db.update_task_status(task_id, TASK_STATUS_PROCESSING, progress=progress)

        # Kiểm tra xem có line config không -> dispatch
        line_config = db.get_line_config(task_id)

        if line_config:
            # === CHẾ ĐỘ THỦ CÔNG ===
            print(f"[Process] Task {task_id} - Using MANUAL mode")
            from processing.process_manual import process_video_file_manual
            import supervision as sv

            trigger_anchor_str = line_config.get("trigger_anchor", "BOTTOM_CENTER")
            trigger_anchor = sv.Position[trigger_anchor_str]

            results = process_video_file_manual(
                video_path,
                str(output_video),
                str(output_json),
                lines=line_config["lines"],
                callback=progress_callback,
                trigger_anchor=trigger_anchor,
            )
        else:
            # === CHẾ ĐỘ TỰ ĐỘNG ===
            print(f"[Process] Task {task_id} - Using AUTO mode")
            from processing.process import process_video_file

            results = process_video_file(
                video_path,
                str(output_video),
                str(output_json),
                callback=progress_callback,
            )

        # Update task to done
        db.update_task_status(task_id, TASK_STATUS_DONE, progress=100)
        
        print(f"✅ Task {task_id} completed successfully!")
        print(f"   Summary: {results['summary']}")
    
    except Exception as e:
        error_msg = f"Processing error: {str(e)}"
        print(f"❌ Task {task_id} failed: {error_msg}")
        db.update_task_status(task_id, TASK_STATUS_FAILED, error_msg=error_msg)


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
