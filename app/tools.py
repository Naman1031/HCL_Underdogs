"""
Deterministic student tools (spec D.7) [BRIEF R5, R7]. Every tool takes
student_id as its first argument, supplied by the graph from the X-Student-Id
header and never by the LLM, and returns a ToolResult. Thresholds come only
from rule_registry via precedence.resolve_rules(), never from constants here,
so tools and policy answers always agree on which rule is in force.
"""

import time
from datetime import date

from app import db, precedence
from app.schemas import Resolution, StudentProfile, ToolResult

# Month order for exam_session values like "2026-MAY", so "latest first" is by date, not alphabet.
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
PASS = "PASS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _result(tool: str, tool_input: dict, output: dict, started: float,
            rule_ids: list[str] | None = None, status: str = "ok") -> ToolResult:
    return ToolResult(tool=tool, input=tool_input, output=output, rule_ids=rule_ids or [],
                      status=status, ms=round((time.perf_counter() - started) * 1000, 2))


def _error(tool: str, tool_input: dict, message: str, started: float) -> ToolResult:
    return _result(tool, tool_input, {"error": message}, started, status="error")


def _session_key(exam_session: str) -> tuple[int, int]:
    """'2026-JUL' -> (2026, 7). Unknown formats sort first."""
    year, _, month = exam_session.partition("-")
    month = month.upper()[:3]
    return (int(year) if year.isdigit() else 0, MONTHS.index(month) + 1 if month in MONTHS else 0)


def _results_rows(student_id: str, course_code: str | None = None) -> list[dict]:
    """Result rows, latest session first (a SUPPLEMENTARY after a REGULAR in the same course wins)."""
    sql = "SELECT * FROM results WHERE student_id = ?"
    params: tuple = (student_id,)
    if course_code:
        sql += " AND course_code = ?"
        params += (course_code,)
    rows = db.query(sql, params)
    return sorted(rows, key=lambda r: (_session_key(r["exam_session"]), r["exam_type"] == "SUPPLEMENTARY"),
                  reverse=True)


def _latest_results(student_id: str) -> dict[str, str]:
    """course_code -> latest result, for counting backlogs."""
    latest: dict[str, str] = {}
    for row in _results_rows(student_id):
        latest.setdefault(row["course_code"], row["result"])
    return latest


def _rule(parameter: str, student: StudentProfile, as_of_date: str) -> Resolution:
    """The rule in force for this student, decided by Person A's precedence resolver (Annex A)."""
    return precedence.resolve_rules(db.get_rules(parameter), db.get_sources(),
                                    date.fromisoformat(as_of_date), student.model_dump())


def _meets(actual: float, operator: str, threshold: str) -> bool:
    if operator == ">=":
        return actual >= float(threshold)
    if operator == "<=":
        return actual <= float(threshold)
    raise ValueError(f"operator {operator!r} is not a numeric comparison")


def _uncertain(tool: str, tool_input: dict, parameter: str, resolution: Resolution, started: float) -> ToolResult:
    """Safety net (spec D.6 step 5): never guess an eligibility result when the rule is unclear."""
    ids = [r.rule_id for r in resolution.conflicts]
    return _result(tool, tool_input, {"result": "RULE_UNCERTAIN", "parameter": parameter,
                                      "reason": resolution.decision_text or resolution.status}, started, ids)


# ---------------------------------------------------------------------------
# Lookups used by the graph and the guardrail
# ---------------------------------------------------------------------------
def get_student(student_id: str) -> StudentProfile | None:
    """The student's profile, or None if the ID is not in the students table."""
    rows = db.query("SELECT student_id, programme, batch_year, current_semester, cgpa, active_backlogs "
                    "FROM students WHERE student_id = ?", (student_id,))
    return StudentProfile(**rows[0]) if rows else None


def list_courses(student_id: str) -> list[dict]:
    """The student's courses (with attendance or results) as [{"course_code", "course_name"}]."""
    return db.query(
        "SELECT DISTINCT c.course_code, c.course_name FROM courses c "
        "WHERE c.course_code IN (SELECT course_code FROM attendance WHERE student_id = ? "
        "                        UNION SELECT course_code FROM results WHERE student_id = ?) "
        "ORDER BY c.course_code", (student_id, student_id))


# ---------------------------------------------------------------------------
# The six tools (spec D.7)
# ---------------------------------------------------------------------------
def get_student_profile(student_id: str) -> ToolResult:
    """programme, batch_year, semester, cgpa, active_backlogs."""
    started, tool_input = time.perf_counter(), {}
    student = get_student(student_id)
    if student is None:
        return _error("get_student_profile", tool_input, f"No student record for {student_id}.", started)
    return _result("get_student_profile", tool_input, {
        "programme": student.programme, "batch_year": student.batch_year,
        "semester": student.current_semester, "cgpa": student.cgpa,
        "active_backlogs": student.active_backlogs}, started)


def get_attendance(student_id: str, course_code: str) -> ToolResult:
    """classes_held, classes_attended, attendance_pct (2 dp, computed, never stored)."""
    started, tool_input = time.perf_counter(), {"course_code": course_code}
    rows = db.query("SELECT classes_held, classes_attended FROM attendance "
                    "WHERE student_id = ? AND course_code = ?", (student_id, course_code))
    if not rows:
        return _error("get_attendance", tool_input, f"No attendance record for {course_code}.", started)
    held, attended = rows[0]["classes_held"], rows[0]["classes_attended"]
    return _result("get_attendance", tool_input, {
        "classes_held": held, "classes_attended": attended,
        "attendance_pct": round(attended * 100 / held, 2)}, started)


def get_results(student_id: str, course_code: str | None = None) -> ToolResult:
    """Rows from results, latest session first; all courses if course_code is None."""
    started, tool_input = time.perf_counter(), {"course_code": course_code}
    rows = _results_rows(student_id, course_code)
    if not rows:
        what = f"for {course_code}" if course_code else "for you"
        return _error("get_results", tool_input, f"No exam results {what}.", started)
    fields = ("course_code", "exam_session", "exam_type", "internal_marks", "external_marks",
              "total_marks", "max_marks", "result")
    return _result("get_results", tool_input, {"results": [{k: r[k] for k in fields} for r in rows]}, started)


def check_exam_eligibility(student_id: str, course_code: str, as_of_date: str) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, attendance_pct, threshold, rule_id."""
    started = time.perf_counter()
    tool_input = {"course_code": course_code, "as_of_date": as_of_date}
    student = get_student(student_id)
    attendance = get_attendance(student_id, course_code)
    if student is None or attendance.status == "error":
        message = attendance.output.get("error", f"No student record for {student_id}.")
        return _error("check_exam_eligibility", tool_input, message, started)

    resolution = _rule("min_attendance_pct", student, as_of_date)
    if resolution.status != "RESOLVED":
        return _uncertain("check_exam_eligibility", tool_input, "min_attendance_pct", resolution, started)
    rule, pct = resolution.winner, attendance.output["attendance_pct"]
    # Rule min_attendance_pct (e.g. ATT-MIN-01, ACAD-ORD-2022 R.1(B).22): attendance % must meet the minimum.
    eligible = _meets(pct, rule.operator, rule.value)
    return _result("check_exam_eligibility", tool_input, {
        "result": "ELIGIBLE" if eligible else "NOT_ELIGIBLE", "attendance_pct": pct,
        "classes_attended": attendance.output["classes_attended"],
        "classes_held": attendance.output["classes_held"],
        "threshold": float(rule.value), "rule_id": rule.rule_id}, started, [rule.rule_id])


def check_supplementary_eligibility(student_id: str, course_code: str, as_of_date: str) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, reason, rule_ids."""
    started = time.perf_counter()
    tool_input = {"course_code": course_code, "as_of_date": as_of_date}
    student = get_student(student_id)
    rows = _results_rows(student_id, course_code)
    if student is None or not rows:
        return _error("check_supplementary_eligibility", tool_input,
                      f"No exam result for {course_code}.", started)

    resolution = _rule("supplementary_allowed_results", student, as_of_date)
    if resolution.status != "RESOLVED":
        return _uncertain("check_supplementary_eligibility", tool_input,
                          "supplementary_allowed_results", resolution, started)
    rule, latest = resolution.winner, rows[0]
    # Rule supplementary_allowed_results (SUPP-ELIG-01, ACAD-CIRC-2026-08 clause 3.2), operator "in":
    # only the listed results (e.g. FAIL;ABSENT) may register. DETAINED must repeat the course.
    allowed = [v.strip().upper() for v in rule.value.split(";") if v.strip()]
    eligible = latest["result"] in allowed
    reason = (f"Your latest result in {course_code} is {latest['result']} ({latest['exam_session']}); "
              f"the supplementary exam is open to: {', '.join(allowed)}.")
    return _result("check_supplementary_eligibility", tool_input, {
        "result": "ELIGIBLE" if eligible else "NOT_ELIGIBLE", "latest_result": latest["result"],
        "exam_session": latest["exam_session"], "allowed_results": allowed, "reason": reason,
        "rule_id": rule.rule_id}, started, [rule.rule_id])


def check_placement_eligibility(
    student_id: str, as_of_date: str, assume_passed: list[str] | None = None
) -> ToolResult:
    """ELIGIBLE / NOT_ELIGIBLE / RULE_UNCERTAIN, cgpa, backlogs, thresholds, rule_ids.

    assume_passed lists course codes treated as PASS for what-if questions (spec D.3 node 6).
    """
    started = time.perf_counter()
    assume = sorted({c.upper() for c in assume_passed or []})
    tool_input = {"as_of_date": as_of_date, "assume_passed": assume}
    student = get_student(student_id)
    if student is None:
        return _error("check_placement_eligibility", tool_input, f"No student record for {student_id}.", started)

    # What-if: each assumed course that is currently a backlog stops counting as one.
    latest = _latest_results(student_id)
    cleared = [c for c in assume if latest.get(c) not in (None, PASS)]
    backlogs = max(student.active_backlogs - len(cleared), 0)

    cgpa_rule = _rule("placement_min_cgpa", student, as_of_date)
    backlog_rule = _rule("placement_max_backlogs", student, as_of_date)
    for parameter, resolution in (("placement_min_cgpa", cgpa_rule), ("placement_max_backlogs", backlog_rule)):
        if resolution.status != "RESOLVED":
            return _uncertain("check_placement_eligibility", tool_input, parameter, resolution, started)

    # Rules PLACE-CGPA-01 / PLACE-BACK-01 (ACAD-CIRC-2026-08 clauses 4.1, 4.2): both must hold.
    failed = []
    if not _meets(student.cgpa, cgpa_rule.winner.operator, cgpa_rule.winner.value):
        failed.append(f"CGPA {student.cgpa} is below the minimum of {cgpa_rule.winner.value}")
    if not _meets(backlogs, backlog_rule.winner.operator, backlog_rule.winner.value):
        failed.append(f"{backlogs} active backlog(s) is above the maximum of {backlog_rule.winner.value}")
    rule_ids = [cgpa_rule.winner.rule_id, backlog_rule.winner.rule_id]
    return _result("check_placement_eligibility", tool_input, {
        "result": "NOT_ELIGIBLE" if failed else "ELIGIBLE", "cgpa": student.cgpa,
        "backlogs": backlogs, "backlogs_before_assumptions": student.active_backlogs,
        "assumed_passed": cleared, "min_cgpa": float(cgpa_rule.winner.value),
        "max_backlogs": float(backlog_rule.winner.value), "failed_checks": failed,
        "rule_ids": rule_ids}, started, rule_ids)
