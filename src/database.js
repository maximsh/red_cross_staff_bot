import Database from 'better-sqlite3';
import { mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DB_PATH = join(__dirname, '..', 'data', 'hr.db');

let db;

export function initDb() {
  // Ensure data directory exists
  mkdirSync(dirname(DB_PATH), { recursive: true });

  db = new Database(DB_PATH);

  // Enable WAL mode for better concurrent reads
  db.pragma('journal_mode = WAL');

  db.exec(`
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
  `);

  return db;
}

export function getDb() {
  if (!db) throw new Error('Database not initialized. Call initDb() first.');
  return db;
}

/**
 * Create or update employee record
 */
export function upsertEmployee(telegramId, firstName, lastName = '', username = '') {
  const stmt = getDb().prepare(`
    INSERT INTO employees (telegram_id, first_name, last_name, username)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
      first_name = excluded.first_name,
      last_name = excluded.last_name,
      username = excluded.username
  `);
  stmt.run(telegramId, firstName, lastName, username);

  // Ensure current_status row exists
  const statusStmt = getDb().prepare(`
    INSERT OR IGNORE INTO current_status (telegram_id, status)
    VALUES (?, 'offline')
  `);
  statusStmt.run(telegramId);
}

/**
 * Record an event (checkin/checkout/field_start/field_end)
 * and update current_status accordingly
 */
export function recordEvent(telegramId, eventType, note = '') {
  const now = new Date().toISOString();

  const insertEvent = getDb().prepare(`
    INSERT INTO events (telegram_id, event_type, note, created_at)
    VALUES (?, ?, ?, ?)
  `);

  const statusMap = {
    checkin: 'in_office',
    checkout: 'offline',
    field_start: 'field_trip',
    field_end: 'in_office',
  };

  const newStatus = statusMap[eventType];
  if (!newStatus) throw new Error(`Unknown event type: ${eventType}`);

  const updateStatus = getDb().prepare(`
    INSERT INTO current_status (telegram_id, status, last_event_at)
    VALUES (?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
      status = excluded.status,
      last_event_at = excluded.last_event_at
  `);

  const transaction = getDb().transaction(() => {
    insertEvent.run(telegramId, eventType, note, now);
    updateStatus.run(telegramId, newStatus, now);
  });

  transaction();

  return { status: newStatus, eventType, timestamp: now };
}

/**
 * Get current status for a specific employee
 */
export function getCurrentStatus(telegramId) {
  const stmt = getDb().prepare(`
    SELECT e.telegram_id, e.first_name, e.last_name, e.username,
           COALESCE(cs.status, 'offline') as status,
           cs.last_event_at
    FROM employees e
    LEFT JOIN current_status cs ON e.telegram_id = cs.telegram_id
    WHERE e.telegram_id = ?
  `);
  return stmt.get(telegramId);
}

/**
 * Get all employees with their current status
 */
export function getAllStatuses() {
  const stmt = getDb().prepare(`
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
  `);
  return stmt.all();
}

/**
 * Get today's events for a specific employee
 * Uses Europe/Kyiv timezone
 */
export function getTodayEvents(telegramId) {
  // Calculate today's date range in UTC based on Kyiv timezone (UTC+3)
  const now = new Date();
  const kyivOffset = 3 * 60; // minutes
  const kyivNow = new Date(now.getTime() + (kyivOffset + now.getTimezoneOffset()) * 60000);
  const todayStart = new Date(kyivNow);
  todayStart.setHours(0, 0, 0, 0);
  const todayStartUTC = new Date(todayStart.getTime() - (kyivOffset * 60000));

  const stmt = getDb().prepare(`
    SELECT id, event_type, note, created_at
    FROM events
    WHERE telegram_id = ? AND created_at >= ?
    ORDER BY created_at ASC
  `);
  return stmt.all(telegramId, todayStartUTC.toISOString());
}

/**
 * Get valid next actions based on current status
 */
export function getValidActions(status) {
  switch (status) {
    case 'offline':
      return ['checkin'];
    case 'in_office':
      return ['checkout', 'field_start'];
    case 'field_trip':
      return ['field_end'];
    default:
      return ['checkin'];
  }
}
