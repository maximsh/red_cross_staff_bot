import sqlite3
import os
import threading
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")

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
              photo_url TEXT DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS deleted_employees (
              telegram_id INTEGER PRIMARY KEY,
              deleted_at DATETIME DEFAULT (datetime('now')),
              deleted_by INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS monitored_topics (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id INTEGER NOT NULL,
              thread_id INTEGER NOT NULL,
              topic_type TEXT NOT NULL DEFAULT 'trips',
              topic_name TEXT DEFAULT '',
              created_at DATETIME DEFAULT (datetime('now')),
              UNIQUE(chat_id, thread_id, topic_type)
            );

            CREATE INDEX IF NOT EXISTS idx_monitored_topics ON monitored_topics(chat_id, thread_id, topic_type);

            CREATE TABLE IF NOT EXISTS system_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at DATETIME DEFAULT (datetime('now'))
            );
            """)
            
            # Add photo_url column if it doesn't exist
            try:
                conn.execute("ALTER TABLE employees ADD COLUMN photo_url TEXT DEFAULT '';")
            except sqlite3.OperationalError:
                pass
            
            # Add aliases column if it doesn't exist
            try:
                conn.execute("ALTER TABLE employees ADD COLUMN aliases TEXT DEFAULT '';")
            except sqlite3.OperationalError:
                pass

            conn.commit()
        finally:
            conn.close()

def is_deleted_employee(telegram_id: int) -> bool:
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM deleted_employees WHERE telegram_id = ?", (telegram_id,))
            return cur.fetchone() is not None
        finally:
            conn.close()

def get_employee(telegram_id: int):
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM employees WHERE telegram_id = ?", (telegram_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

def get_employee_by_username(username: str):
    username = username.lstrip('@').lower()
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM employees WHERE LOWER(username) = ?", (username,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

def upsert_employee(telegram_id: int, first_name: str, last_name: str = '', username: str = '', photo_url: str = ''):
    with db_lock:
        conn = get_db_connection()
        try:
            # Check if this user was deleted
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM deleted_employees WHERE telegram_id = ?", (telegram_id,))
            if cur.fetchone():
                return False

            conn.execute("""
                INSERT INTO employees (telegram_id, first_name, last_name, username, photo_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                  first_name = excluded.first_name,
                  last_name = excluded.last_name,
                  username = excluded.username,
                  photo_url = CASE WHEN excluded.photo_url != '' THEN excluded.photo_url ELSE employees.photo_url END
            """, (telegram_id, first_name, last_name or '', username or '', photo_url or ''))

            # Ensure current_status row exists
            conn.execute("""
                INSERT OR IGNORE INTO current_status (telegram_id, status)
                VALUES (?, 'offline')
            """, (telegram_id,))
            conn.commit()
            return True
        finally:
            conn.close()

def delete_employee(telegram_id: int, deleted_by: int = None):
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")
            now = get_iso_now()
            # Record in deleted_employees table to prevent auto-registration
            conn.execute("""
                INSERT OR REPLACE INTO deleted_employees (telegram_id, deleted_at, deleted_by)
                VALUES (?, ?, ?)
            """, (telegram_id, now, deleted_by))

            # Delete from current_status
            conn.execute("DELETE FROM current_status WHERE telegram_id = ?", (telegram_id,))

            # Delete from events
            conn.execute("DELETE FROM events WHERE telegram_id = ?", (telegram_id,))

            # Delete from employees
            conn.execute("DELETE FROM employees WHERE telegram_id = ?", (telegram_id,))

            conn.commit()
            return True
        except Exception as e:
            conn.execute("ROLLBACK;")
            raise e
        finally:
            conn.close()

def restore_employee(telegram_id: int):
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM deleted_employees WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return True
        finally:
            conn.close()

def set_employee_aliases(telegram_id: int, aliases: str):
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("UPDATE employees SET aliases = ? WHERE telegram_id = ?", (aliases, telegram_id))
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
                SELECT e.telegram_id, e.first_name, e.last_name, e.username, e.photo_url, e.aliases,
                       COALESCE(cs.status, 'offline') as status,
                       cs.last_event_at,
                       (SELECT note FROM events ev WHERE ev.telegram_id = e.telegram_id ORDER BY ev.created_at DESC LIMIT 1) as note
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
                SELECT e.telegram_id, e.first_name, e.last_name, e.username, e.photo_url, e.aliases,
                       COALESCE(cs.status, 'offline') as status,
                       cs.last_event_at,
                       (SELECT note FROM events ev WHERE ev.telegram_id = e.telegram_id ORDER BY ev.created_at DESC LIMIT 1) as note
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
    # Calculate today's date range in UTC based on Kyiv timezone
    now_kyiv = datetime.now(KYIV_TZ)
    today_start_kyiv = now_kyiv.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_kyiv.astimezone(timezone.utc)
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
        return ['checkout', 'field_start', 'checkin']
    elif status == 'field_trip':
        return ['field_end', 'checkout', 'checkin']
    else:
        return ['checkin', 'field_start']

def set_main_topic(chat_id: int, thread_id: int, topic_name: str = '') -> bool:
    """Replace any existing main topic for this chat so only one branch is monitored."""
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                DELETE FROM monitored_topics
                WHERE chat_id = ? AND topic_type = 'main'
            """, (chat_id,))
            conn.execute("""
                INSERT INTO monitored_topics (chat_id, thread_id, topic_type, topic_name)
                VALUES (?, ?, 'main', ?)
            """, (chat_id, thread_id, topic_name or ''))
            conn.commit()
            return True
        finally:
            conn.close()

def add_monitored_topic(chat_id: int, thread_id: int, topic_type: str = 'trips', topic_name: str = '') -> bool:
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO monitored_topics (chat_id, thread_id, topic_type, topic_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, thread_id, topic_type) DO UPDATE SET
                  topic_name = excluded.topic_name
            """, (chat_id, thread_id, topic_type, topic_name or ''))
            conn.commit()
            return True
        finally:
            conn.close()

def remove_monitored_topic(chat_id: int, thread_id: int, topic_type: str = 'trips') -> bool:
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                DELETE FROM monitored_topics
                WHERE chat_id = ? AND thread_id = ? AND topic_type = ?
            """, (chat_id, thread_id, topic_type))
            conn.commit()
            return True
        finally:
            conn.close()

def get_monitored_topics(topic_type: str = None):
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            if topic_type:
                cur.execute("SELECT * FROM monitored_topics WHERE topic_type = ? ORDER BY id DESC", (topic_type,))
            else:
                cur.execute("SELECT * FROM monitored_topics ORDER BY id DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def _get_env_topic(topic_type: str):
    if topic_type == 'trips':
        return os.getenv("TRIPS_CHAT_ID"), os.getenv("TRIPS_THREAD_ID")
    if topic_type == 'main':
        return os.getenv("MAIN_CHAT_ID"), os.getenv("MAIN_THREAD_ID")
    return None, None

def has_monitored_topics(chat_id: int, topic_type: str = 'main') -> bool:
    env_chat, env_thread = _get_env_topic(topic_type)
    if env_chat and env_thread:
        try:
            if int(env_chat) == chat_id and env_thread.strip().isdigit():
                return True
        except ValueError:
            pass

    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM monitored_topics
                WHERE chat_id = ? AND topic_type = ?
                LIMIT 1
            """, (chat_id, topic_type))
            return cur.fetchone() is not None
        finally:
            conn.close()

def is_topic_monitored(chat_id: int, thread_id: int = None, topic_type: str = 'trips') -> bool:
    # 1. Check environment variables
    env_chat, env_thread = _get_env_topic(topic_type)
    if env_chat and env_thread:
        try:
            if int(env_chat) == chat_id and (thread_id is not None and int(env_thread) == thread_id):
                return True
        except ValueError:
            pass

    if thread_id is None:
        return False

    # 2. Check database
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM monitored_topics
                WHERE chat_id = ? AND thread_id = ? AND topic_type = ?
            """, (chat_id, thread_id, topic_type))
            return cur.fetchone() is not None
        finally:
            conn.close()

def set_setting(key: str, value: str):
    with db_lock:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
            """, (key, str(value)))
            conn.commit()
        finally:
            conn.close()

def get_setting(key: str, default: str = None) -> str:
    with db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

def get_main_chat_id():
    env_val = os.getenv("MAIN_CHAT_ID")
    if env_val and env_val.strip().lstrip("-").isdigit():
        return int(env_val.strip())
    db_val = get_setting("main_chat_id")
    if db_val and db_val.strip().lstrip("-").isdigit():
        return int(db_val.strip())
    return None

def set_main_chat_id(chat_id: int):
    set_setting("main_chat_id", str(chat_id))


