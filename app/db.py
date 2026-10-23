"""
SQLite access through the built-in sqlite3 module (no ORM, for readability).
Creates the Annex C tables exactly as the brief specifies (judges load their
own data into them, so never rename a column), plus our own `sources` and
`audit_log` tables (spec F.2). Each call opens its own connection, which keeps
it safe under FastAPI's worker threads.
"""

import sqlite3
from typing import Any

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
  student_id TEXT PRIMARY KEY,
  full_name TEXT NOT NULL,
  programme TEXT NOT NULL,
  batch_year INTEGER NOT NULL,
  current_semester INTEGER NOT NULL CHECK (current_semester BETWEEN 1 AND 10),
  cgpa REAL NOT NULL CHECK (cgpa BETWEEN 0 AND 10),
  active_backlogs INTEGER NOT NULL CHECK (active_backlogs >= 0)
);
CREATE TABLE IF NOT EXISTS courses (
  course_code TEXT PRIMARY KEY,
  course_name TEXT NOT NULL,
  programme TEXT NOT NULL,
  semester INTEGER NOT NULL,
  credits INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attendance (
  student_id TEXT NOT NULL REFERENCES students(student_id),
  course_code TEXT NOT NULL REFERENCES courses(course_code),
  classes_held INTEGER NOT NULL CHECK (classes_held > 0),
  classes_attended INTEGER NOT NULL CHECK (classes_attended >= 0 AND classes_attended <= classes_held),
  PRIMARY KEY (student_id, course_code)
);
CREATE TABLE IF NOT EXISTS results (
  student_id TEXT NOT NULL REFERENCES students(student_id),
  course_code TEXT NOT NULL REFERENCES courses(course_code),
  exam_session TEXT NOT NULL,
  exam_type TEXT NOT NULL CHECK (exam_type IN ('REGULAR','SUPPLEMENTARY')),
  internal_marks INTEGER NOT NULL,
  external_marks INTEGER NOT NULL,
  total_marks INTEGER NOT NULL,
  max_marks INTEGER NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('PASS','FAIL','ABSENT','DETAINED'))
);
CREATE TABLE IF NOT EXISTS rule_registry (
  rule_id TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  parameter TEXT NOT NULL,
  operator TEXT NOT NULL,
  value TEXT NOT NULL,
  scope_programmes TEXT NOT NULL,
  scope_batches TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  source_doc_id TEXT NOT NULL,
  source_section TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS sources (
  doc_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  issuer TEXT NOT NULL,
  authority_level INTEGER NOT NULL CHECK (authority_level BETWEEN 1 AND 5),
  doc_type TEXT NOT NULL,
  version TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  supersedes TEXT,
  scope_programmes TEXT NOT NULL,
  scope_batches TEXT NOT NULL,
  provenance TEXT,
  retrieved_on TEXT,
  synthetic TEXT NOT NULL,
  chunks_indexed INTEGER,
  ingested_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  trace_id TEXT PRIMARY KEY,
  timestamp TEXT NOT NULL,
  student_id TEXT,
  question_category TEXT,
  answer_type TEXT,
  record_json TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row  # rows can be turned into dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Creates any missing tables. Safe to run on every start."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """Runs one write statement and commits. Returns the number of rows changed."""
    conn = connect()
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def execute_many(sql: str, rows: list[tuple]) -> None:
    """Runs one write statement for many rows in a single transaction."""
    conn = connect()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def get_rules(parameter: str) -> list[dict[str, Any]]:
    """Every rule_registry row for one parameter. Precedence picks the winner, not SQL."""
    return query("SELECT * FROM rule_registry WHERE parameter = ?", (parameter,))


def get_sources() -> list[dict[str, Any]]:
    """Every Source Register row, highest authority first (used by GET /sources)."""
    return query("SELECT * FROM sources ORDER BY authority_level, doc_id")


def health() -> str:
    try:
        query("SELECT 1")
        return "ok"
    except sqlite3.Error:
        return "error"
