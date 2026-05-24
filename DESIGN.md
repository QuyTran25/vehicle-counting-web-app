# DESIGN.md — Vehicle Counting Web App
> Phiên bản: 1.0 | Cập nhật: 24/05/2026

---

## 1. Class IDs YOLO (COCO Dataset)

YOLOv8n được train trên COCO 80-class. Các loại xe **được đếm** trong dự án này:

| Tên hiển thị | COCO Class Name | Class ID | Lý do chọn |
|---|---|---|---|
| Xe ô tô | `car` | **2** | Phổ biến nhất trên đường phố |
| Xe máy | `motorcycle` | **3** | Chiếm đa số tại VN |
| Xe buýt | `bus` | **5** | Phương tiện công cộng lớn |
| Xe tải | `truck` | **7** | Tải trọng lớn, cần giám sát |

```python
# processing/process.py — dùng constant này
VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}
CLASS_IDS = list(VEHICLE_CLASSES.keys())  # [2, 3, 5, 7]
```

> ⚠️ Lưu ý: COCO dùng `motorcycle` (ID=3), **không phải** `motorbike`.
> Xe đạp (bicycle, ID=1) và xe đạp điện **không** được đếm — YOLO thường nhận diện chúng kém chính xác.

---

## 2. Database Schema (SQLite)

File: `database.db` tại root project.

### Bảng `tasks`

| Cột | Kiểu | Mô tả |
|---|---|---|
| `id` | TEXT PK | UUID của task |
| `filename` | TEXT | Tên file video gốc |
| `status` | TEXT | `queued` / `processing` / `done` / `failed` |
| `progress` | INTEGER | 0–100 (%) |
| `error_msg` | TEXT | Mô tả lỗi nếu `failed` |
| `created_at` | TEXT | ISO-8601 datetime |
| `updated_at` | TEXT | ISO-8601 datetime |

### Bảng `results`

| Cột | Kiểu | Mô tả |
|---|---|---|
| `task_id` | TEXT PK/FK | Tham chiếu `tasks.id` |
| `video_duration` | REAL | Thời lượng video (giây) |
| `fps` | REAL | FPS của video |
| `total_frames` | INTEGER | Tổng số frame |
| `resolution` | TEXT | Ví dụ: `1920x1080` |
| `car_count` | INTEGER | Tổng xe ô tô đếm được |
| `motorcycle_count` | INTEGER | Tổng xe máy |
| `bus_count` | INTEGER | Tổng xe buýt |
| `truck_count` | INTEGER | Tổng xe tải |
| `timeline_json` | TEXT | JSON array — đếm theo từng giây |
| `events_json` | TEXT | JSON array — từng sự kiện crossing |
| `output_video` | TEXT | Đường dẫn file `.mp4` output |
| `output_json` | TEXT | Đường dẫn file `.json` output |

---

## 3. API Contract

Base URL: `http://localhost:8000`

### POST `/upload`
Upload video để xử lý.

**Request:** `multipart/form-data`
```
file: <video.mp4>
```

**Response 200:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Video uploaded successfully"
}
```

---

### GET `/status/{task_id}`
Polling trạng thái xử lý (frontend gọi mỗi 2 giây).

**Response 200:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 45,
  "error_msg": null
}
```

**Các giá trị `status`:**
- `queued` — Đang chờ trong hàng đợi
- `processing` — AI engine đang chạy
- `done` — Hoàn thành
- `failed` — Lỗi (xem `error_msg`)

---

### GET `/result/{task_id}`
Lấy kết quả sau khi `status = done`.

**Response 200:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "metadata": {
    "video_duration": 60,
    "fps": 30,
    "total_frames": 1800,
    "resolution": "1920x1080"
  },
  "summary": {
    "car": 120,
    "motorcycle": 210,
    "bus": 8,
    "truck": 20
  },
  "timeline": [
    { "second": 1, "car": 2, "motorcycle": 3, "bus": 0, "truck": 0 },
    { "second": 2, "car": 1, "motorcycle": 5, "bus": 1, "truck": 0 }
  ],
  "events": [
    {
      "frame": 201,
      "timestamp": 6.7,
      "track_id": 15,
      "class": "motorcycle",
      "direction": "in"
    }
  ],
  "output_video": "outputs/550e8400_output.mp4",
  "output_json": "outputs/550e8400_result.json"
}
```

---

### GET `/tasks`
Danh sách tất cả task đã xử lý.

**Response 200:**
```json
[
  {
    "task_id": "550e8400-...",
    "filename": "traffic_cam_01.mp4",
    "status": "done",
    "progress": 100,
    "created_at": "2026-05-24T10:00:00"
  }
]
```

---

## 4. JSON Schema — Output AI Engine

File lưu tại `outputs/<task_id>_result.json`:

```json
{
  "metadata": {
    "video_duration": 60,
    "fps": 30,
    "total_frames": 1800,
    "resolution": "1920x1080"
  },
  "summary": {
    "car": 120,
    "motorcycle": 210,
    "bus": 8,
    "truck": 20
  },
  "timeline": [
    {
      "second": 1,
      "car": 2,
      "motorcycle": 3,
      "bus": 0,
      "truck": 0
    }
  ],
  "events": [
    {
      "frame": 201,
      "timestamp": 6.7,
      "track_id": 15,
      "class": "motorcycle",
      "direction": "in"
    }
  ]
}
```

### Giải thích các trường

| Trường | Mô tả |
|---|---|
| `metadata` | Thông tin kỹ thuật của video đầu vào |
| `summary` | Tổng số xe mỗi loại đi qua line |
| `timeline` | Mảng đếm xe **theo từng giây** — dùng để vẽ biểu đồ |
| `events` | Mỗi phần tử = 1 lần 1 xe cắt qua LineZone |
| `events[].direction` | `"in"` hoặc `"out"` (tùy chiều đặt line) |
| `events[].track_id` | ID do ByteTrack gán — dùng để tránh đếm trùng |

---

## 5. Cấu trúc thư mục (Lock-in)

```
/vehicle-counter-project
├── app/
│   ├── main.py              # FastAPI routes
│   ├── database.py          # SQLite CRUD
│   ├── task_manager.py      # Quản lý hàng đợi task
│   └── process_runner.py    # Gọi subprocess AI engine
├── processing/
│   ├── process.py           # YOLO + ByteTrack + LineZone
│   └── utils.py             # Validation video
├── uploads/                 # Video người dùng upload
├── outputs/                 # .mp4 + .json kết quả
├── static/                  # CSS, JS
├── templates/               # HTML Jinja2
├── models/                  # yolov8n.pt
├── tests/                   # Unit tests
├── database.db              # SQLite file
├── requirements.txt
├── DESIGN.md                # File này
└── README.md
```

---

## 6. Hằng số toàn cục (dùng chung giữa các module)

```python
# app/config.py (tạo thêm file này để tránh hardcode)
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CLASS_IDS       = [2, 3, 5, 7]
UPLOADS_DIR     = "uploads"
OUTPUTS_DIR     = "outputs"
DB_PATH         = "database.db"
LINE_START      = (0, 540)    # Tọa độ điểm đầu LineZone — chỉnh theo video
LINE_END        = (1920, 540) # Tọa độ điểm cuối LineZone
CONF_THRESHOLD  = 0.35        # Ngưỡng confidence YOLO
```
