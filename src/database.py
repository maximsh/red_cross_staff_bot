import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'hr.db')
db_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db_lock:
        conn = get_db_connection()
        try:
            # Enable WAL mode for better concurrent reads
            conn.execute("PRAGMA journal_mode = WAL;")

            conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
              telegram_id INTEGER PRIMARY KEY,
              first_name TEXT NOT NULL,
              last_name TEXT DEFAULT '',
              username TEXT DEFAULT '',
              created_at DATETIME DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              telegram_id INTEGER NOT NULL,
              event_type TEXT NOT NULL CHECK(event_type IN ('checkin', 'checkout', 'field_start', 'field_end')),
              note TEXT DEFAULT '',
              created_at DATETIME DEFAULT (datetime('now')),
              FOREIGN KEY (telegram_id) REFERENCES employees(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS current_status (
              telegram_id INTEGER PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'offline' CHECK(status IN ('in_office', 'field_trip', 'offline')),
              last_event_at DATETIME,
              FOREIGN KEY (telegram_id) REFERENCES employees(telegram_id)
            );

            CREATE INDEX IF NOT EXISTS idx_events_telegram_id ON events(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
            """)
            conn.commit()
        finally:
            conn.close()

def upsert_employee(telegram_id: int, first_name: str, last_name: str = '', username: str = ''):
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO employees (telegram_id, first_name, last_name, username)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                  first_name = excluded.first_name,
                  last_name = excluded.last_name,
                  username = excluded.username
            """, (telegram_id, first_name, last_name or '', username or ''))

            # Ensure current_status row exists
            conn.execute("""
                INSERT OR IGNORE INTO current_status (telegram_id, status)
                VALUES (?, 'offline')
            """, (telegram_id,))
            conn.commit()
        finally:
            conn.close()

def get_iso_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def record_event(telegram_id: int, event_type: str, note: str = ''):
    status_map = {
        'checkin': 'in_office',
        'checkout': 'offline',
        'field_start': 'field_trip',
        'field_end': 'in_office'
    }

    new_status = status_map.get(event_type)
    if not new_status:
        raise ValueError(f"Unknown event type: {event_type}")

    now = get_iso_now()

    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")

            conn.execute("""
                INSERT INTO events (telegram_id, event_type, note, created_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, event_type, note or '', now))

            conn.execute("""
                INSERT INTO current_status (telegram_id, status, last_event_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                  status = excluded.status,
                  last_event_at = excluded.last_event_at
            """, (telegram_id, new_status, now))

            conn.commit()
        except Exception as e:
            conn.execute("ROLLBACK;")
            raise e
        finally:
            conn.close()

    return {"status": new_status, "eventType": event_type, "timestamp": now}

def get_current_status(telegram_id: int):
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT e.telegram_id, e.first_name, e.last_name, e.username,
                       COALESCE(cs.status, 'offline') as status,
                       cs.last_event_at
                FROM employees e
                LEFT JOIN current_status cs ON e.telegram_id = cs.telegram_id
                WHERE e.telegram_id = ?
            """, (telegram_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

def get_all_statuses():
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT e.telegram_id, e.first_name, e.last_name, e.username,
                       COALESCE(cs.status, 'offline') as status,
                       cs.last_event_at
                FROM employees e
                LEFT JOIN current_status cs ON e.telegram_id = cs.telegram_id
                ORDER BY
                  CASE COALESCE(cs.status, 'offline')
                    WHEN 'in_office' THEN 1
                    WHEN 'field_trip' THEN 2
                    WHEN 'offline' THEN 3
                  END,
                  e.first_name
            """)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def get_today_events(telegram_id: int):
    # Calculate today's date range in UTC based on Kyiv timezone (UTC+3)
    # This matches the Node.js implementation:
    kyiv_offset = timedelta(hours=3)
    now_utc = datetime.now(timezone.utc)
    kyiv_now = now_utc + kyiv_offset
    today_start_kyiv = kyiv_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_kyiv - kyiv_offset

    today_start_utc_str = today_start_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, event_type, note, created_at
                FROM events
                WHERE telegram_id = ? AND created_at >= ?
                ORDER BY created_at ASC
            """, (telegram_id, today_start_utc_str))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def get_valid_actions(status: str):
    if status == 'offline':
        return ['checkin', 'field_start']
    elif status == 'in_office':
        return ['checkout', 'field_start']
    elif status == 'field_trip':
        return ['field_end', 'checkout']
    else:
        return ['checkin', 'field_start']
