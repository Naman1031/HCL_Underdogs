"""
Audit trail [BRIEF R10, Annex D]: one JSON record per /ask, keyed by trace_id,
stored in the audit_log table and returned by GET /audit/{trace_id}.
Privacy [BRIEF R7]: records never hold the question text or LLM reasoning,
only the Annex D fields (spec F.3).
"""

import json
import uuid

from app import db
from app.schemas import AuditRecord


def new_trace_id() -> str:
    """8 hex characters, like the brief's example "7f3c2a9e"."""
    return uuid.uuid4().hex[:8]


def write(record: AuditRecord) -> None:
    db.execute(
        "INSERT INTO audit_log (trace_id, timestamp, student_id, question_category, answer_type, record_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (record.trace_id, record.timestamp, record.student_id, record.question_category,
         record.answer_type, record.model_dump_json()),
    )


def read(trace_id: str) -> dict | None:
    rows = db.query("SELECT record_json FROM audit_log WHERE trace_id = ?", (trace_id,))
    return json.loads(rows[0]["record_json"]) if rows else None
