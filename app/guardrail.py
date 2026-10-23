"""
Identity and authorisation checks (spec D.3 node 2) [BRIEF R7]. Runs before
any student data is read. The student ID comes only from the X-Student-Id
header; an ID typed in the question is only ever a reason to refuse.
Returns a refusal message (fixed texts from spec G.1) or None to continue.
"""

import re

from app import db
from app.schemas import Category

REFUSE_OTHER_STUDENT = "I can only share your own records."
REFUSE_NOT_LOGGED_IN = "Please log in to ask about your records."

STUDENT_ID_IN_TEXT = re.compile(r"\bS\d{4}\b", re.IGNORECASE)  # Annex C format: S + 4 digits
PERSONAL_CATEGORIES = {"personal_data", "personal_eligibility", "what_if"}


def check(header_student_id: str | None, question: str, category: Category) -> str | None:
    """Refusal message if the request is not allowed, else None."""
    header = (header_student_id or "").strip().upper()

    # Another student's data: by category, or any student ID in the text that is not the caller's.
    mentioned = {m.upper() for m in STUDENT_ID_IN_TEXT.findall(question)}
    if category == "other_student" or mentioned - {header}:
        return REFUSE_OTHER_STUDENT

    if category in PERSONAL_CATEGORIES and not header:
        return REFUSE_NOT_LOGGED_IN

    # A header must name a real student; otherwise nobody is logged in.
    if header and not db.query("SELECT 1 FROM students WHERE student_id = ?", (header,)):
        return REFUSE_NOT_LOGGED_IN
    return None
