"""
Identity and authorisation checks (spec D.3 node 2) [BRIEF R7]. Runs before
any student data is read. The student ID comes only from the X-Student-Id
header; an ID typed in the question is only ever a reason to refuse.
Returns a refusal message (fixed texts from spec G.1) or None to continue.
STUB: final signature with a placeholder body, so Person C can import it.
"""

from app.schemas import Category

REFUSE_OTHER_STUDENT = "I can only share your own records."
REFUSE_NOT_LOGGED_IN = "Please log in to ask about your records."


def check(header_student_id: str | None, question: str, category: Category) -> str | None:
    """Refusal message if the request is not allowed, else None.

    Placeholder until step 5: allows everything. Do not demo personal questions yet.
    """
    return None
