"""SQLite layer (plain sqlite3). Schema, seed data, connection + transaction helpers."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ward_zones (
    zone_id      TEXT PRIMARY KEY CHECK (zone_id IN ('A','B','C','D')),
    name         TEXT NOT NULL,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS doctors (
    doctor_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    zone_id       TEXT NOT NULL REFERENCES ward_zones(zone_id),
    role          TEXT NOT NULL CHECK (role IN ('Primary','Backup')),
    available     INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0,1)),
    max_capacity  INTEGER NOT NULL DEFAULT 3 CHECK (max_capacity >= 0 AND max_capacity <= 50),
    UNIQUE (zone_id, role)
);

CREATE TABLE IF NOT EXISTS reports (
    report_id          TEXT PRIMARY KEY,
    patient_id         TEXT NOT NULL,
    report_code        TEXT NOT NULL,
    category           TEXT NOT NULL CHECK (category IN ('Critical','Stat','Routine','Pending','Error')),
    priority           INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    validation_result  TEXT NOT NULL,
    ward_zone          TEXT NOT NULL,
    reporter_name      TEXT NOT NULL,
    reporter_contact   TEXT NOT NULL,
    description        TEXT,
    urgency            TEXT NOT NULL DEFAULT 'Normal' CHECK (urgency IN ('Normal','Urgent','Emergency')),
    status             TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Assigned','In Progress','Resolved')),
    queue_state        TEXT NOT NULL CHECK (queue_state IN ('Assigned','Waiting','Escalated','Review','Error','Closed')),
    assigned_doctor_id INTEGER REFERENCES doctors(doctor_id),
    routing_decision   TEXT,
    escalation_reason  TEXT,
    submitted_at       TEXT NOT NULL,
    assigned_at        TEXT,
    status_updated_at  TEXT NOT NULL,
    sla_deadline       TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_queue ON reports(queue_state, priority, submitted_at, report_id);
CREATE INDEX IF NOT EXISTS idx_reports_patient ON reports(patient_id);

CREATE TABLE IF NOT EXISTS routing_assignments (
    assignment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       TEXT NOT NULL UNIQUE REFERENCES reports(report_id) ON DELETE CASCADE,  -- one assignment per report
    doctor_id       INTEGER NOT NULL REFERENCES doctors(doctor_id),
    assignment_type TEXT NOT NULL CHECK (assignment_type IN ('Primary','Backup','Manual')),
    assigned_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_status_history (
    history_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    changed_by  TEXT NOT NULL,
    note        TEXT,
    changed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS escalation_records (
    escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    reason        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);

CREATE TABLE IF NOT EXISTS routing_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    decision    TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SEED_ZONES = [("A", "Zone A", "Ward zone A"), ("B", "Zone B", "Ward zone B"),
              ("C", "Zone C", "Ward zone C"), ("D", "Zone D", "Ward zone D")]


def connect(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)  # autocommit; we BEGIN manually
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn):
    """BEGIN IMMEDIATE takes the write lock up-front so concurrent submissions are serialised
    (prevents two requests from grabbing the same doctor capacity / report)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM ward_zones").fetchone()[0] == 0:
        with transaction(conn):
            conn.executemany("INSERT INTO ward_zones VALUES (?,?,?)", SEED_ZONES)
            for z in "ABCD":
                conn.execute("INSERT INTO doctors(name,zone_id,role,available,max_capacity) VALUES (?,?,?,1,3)",
                             (f"Dr. {z}", z, "Primary"))
                conn.execute("INSERT INTO doctors(name,zone_id,role,available,max_capacity) VALUES (?,?,?,1,2)",
                             (f"Dr. {z}1", z, "Backup"))
            conn.execute("INSERT INTO settings VALUES ('clock_offset_minutes','0')")
            conn.execute("INSERT INTO settings VALUES ('report_seq','0')")
    conn.close()


# ---- simulated clock (lets the 15-minute SLA be demonstrated instantly) ---- #
def now(conn) -> datetime:
    row = conn.execute("SELECT value FROM settings WHERE key='clock_offset_minutes'").fetchone()
    return datetime.now(timezone.utc) + timedelta(minutes=int(row[0]) if row else 0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) if s else None


def next_report_id(conn) -> str:
    conn.execute("UPDATE settings SET value = CAST(value AS INTEGER) + 1 WHERE key='report_seq'")
    seq = int(conn.execute("SELECT value FROM settings WHERE key='report_seq'").fetchone()[0])
    return f"RPT-{seq:06d}"
