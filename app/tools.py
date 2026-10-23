"""
Deterministic student tools (spec D.7) [BRIEF R5, R7]. Every tool takes
student_id as its first argument, supplied by the graph from the X-Student-Id
header and never by the LLM, and returns a ToolResult. Thresholds come only
from rule_registry via precedence.resolve_rules(), never from constants here.
STUB: final signatures with placeholder bodies, so Person C can import them.
"""

from app.schemas import StudentProfile, ToolResult


def _not_implemented(tool: str, tool_input: dict) -> ToolResult:
    # Placeholder until step 5; status "error" so nothing treats it as a real answer.
    return ToolResult(tool=tool, input=tool_input, output={"error": "not implemented yet"}, status="error")


def get_student(student_id: str) -> StudentProfile | None:
    """The student's profile, or None if the ID is not in the students table."""
    return None


def list_courses(student_id: str) -> list[dict]:
    """The student's current courses as [{"course_code", "course_name"}], for clarification_needed."""
    return []


def get_student_profile(student_id: str) -> ToolResult:
    """programme, batch_year, semester, cgpa, active_backlogs."""
    return _not_implemented("get_student_profile", {})


def get_attendance(student_id: str, course_code: str) -> ToolResult:
    """classes_held, classes_attended, attendance_pct (2 dp, computed, never stored)."""
    return _not_implemented("get_attendance", {"course_code": course_code})


def get_results(student_id: str, course_code: str | None = None) -> ToolResult:
    """Rows from results, latest session first; all courses if course_code is None."""
    return _not_implemented("get_results", {"course_code": course_code})


def check_exam_eligibility(student_id: str, course_code: str, as_of_date: str) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, attendance_pct, threshold, rule_id."""
    return _not_implemented("check_exam_eligibility", {"course_code": course_code, "as_of_date": as_of_date})


def check_supplementary_eligibility(student_id: str, course_code: str, as_of_date: str) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, reason, rule_ids."""
    return _not_implemented("check_supplementary_eligibility", {"course_code": course_code, "as_of_date": as_of_date})


def check_placement_eligibility(
    student_id: str, as_of_date: str, assume_passed: list[str] | None = None
) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, cgpa, backlogs, thresholds, rule_ids.

    assume_passed lists course codes treated as PASS for what-if questions (spec D.3 node 6).
    """
    tool_input = {"as_of_date": as_of_date, "assume_passed": assume_passed or []}
    return _not_implemented("check_placement_eligibility", tool_input)
