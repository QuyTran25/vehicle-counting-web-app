"""
database.py - Quản lý SQLite cho Vehicle Counting Web App
Chạy trực tiếp để khởi tạo DB: python app/database.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database.db")


def get_connection() -> sqlite3.Connection:
    """Trả về connection tới SQLite, với row_factory để truy cập theo tên cột."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Tạo các bảng nếu chưa tồn tại."""
    conn = get_connection()
    cursor = conn.cursor()

    # Bảng tasks: quản lý trạng thái từng video được upload
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,          -- UUID dạng string
            filename    TEXT NOT NULL,             -- Tên file gốc người dùng upload
            status      TEXT NOT NULL              -- queued | processing | done | failed
                        DEFAULT 'queued',
            progress    INTEGER NOT NULL           -- 0-100 (%)
                        DEFAULT 0,
            error_msg   TEXT,                      -- Mô tả lỗi nếu status = failed
            created_at  TEXT NOT NULL              -- ISO-8601, ví dụ: 2026-05-24T10:00:00
                        DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL
                        DEFAULT (datetime('now'))
        )
    """)

    # Bảng results: lưu kết quả JSON từ AI engine
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            task_id         TEXT PRIMARY KEY,
            video_duration  REAL,                  -- giây
            fps             REAL,
            total_frames    INTEGER,
            resolution      TEXT,                  -- ví dụ: "1920x1080"
            car_count       INTEGER DEFAULT 0,
            motorcycle_count INTEGER DEFAULT 0,
            bus_count       INTEGER DEFAULT 0,
            truck_count     INTEGER DEFAULT 0,
            timeline_json   TEXT,                  -- JSON array theo giây
            events_json     TEXT,                  -- JSON array sự kiện crossing
            output_video    TEXT,                  -- đường dẫn file .mp4 output
            output_json     TEXT,                  -- đường dẫn file .json output
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at: {DB_PATH}")


# ──────────────────────────────────────────
# CRUD helpers
# ──────────────────────────────────────────

def create_task(task_id: str, filename: str) -> None:
    """Tạo task mới với trạng thái 'queued'."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO tasks (id, filename, status, progress) VALUES (?, ?, 'queued', 0)",
        (task_id, filename),
    )
    conn.commit()
    conn.close()


def update_task_status(task_id: str, status: str, progress: int = None, error_msg: str = None) -> None:
    """Cập nhật trạng thái và tiến độ của task."""
    conn = get_connection()
    if progress is not None:
        conn.execute(
            """UPDATE tasks
               SET status = ?, progress = ?, error_msg = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (status, progress, error_msg, task_id),
        )
    else:
        conn.execute(
            """UPDATE tasks
               SET status = ?, error_msg = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (status, error_msg, task_id),
        )
    conn.commit()
    conn.close()


def get_task(task_id: str) -> dict | None:
    """Lấy thông tin 1 task theo ID. Trả về dict hoặc None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_tasks() -> list[dict]:
    """Lấy danh sách tất cả task, sắp xếp mới nhất trước."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_result(task_id: str, result: dict) -> None:
    """Lưu kết quả AI engine vào bảng results."""
    import json

    meta = result.get("metadata", {})
    summary = result.get("summary", {})

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO results
           (task_id, video_duration, fps, total_frames, resolution,
            car_count, motorcycle_count, bus_count, truck_count,
            timeline_json, events_json, output_video, output_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            meta.get("video_duration"),
            meta.get("fps"),
            meta.get("total_frames"),
            meta.get("resolution"),
            summary.get("car", 0),
            summary.get("motorcycle", 0),
            summary.get("bus", 0),
            summary.get("truck", 0),
            json.dumps(result.get("timeline", []), ensure_ascii=False),
            json.dumps(result.get("events", []), ensure_ascii=False),
            result.get("output_video"),
            result.get("output_json"),
        ),
    )
    conn.commit()
    conn.close()


def get_result(task_id: str) -> dict | None:
    """Lấy kết quả của task. Trả về dict hoặc None."""
    import json

    conn = get_connection()
    row = conn.execute("SELECT * FROM results WHERE task_id = ?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return None

    data = dict(row)
    data["timeline"] = json.loads(data.pop("timeline_json") or "[]")
    data["events"] = json.loads(data.pop("events_json") or "[]")
    return data


# ──────────────────────────────────────────
if __name__ == "__main__":
    init_db()
