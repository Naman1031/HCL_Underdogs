"""
Generates the synthetic student data kit (spec F.6) [BRIEF Section 4.2, Annex C].
Code decides the edge-case plan and every boundary number, using thresholds
resolved from rule_registry by precedence.resolve_rules(). The LLM (temperature
0.7) only invents names and the remaining realistic values; each reply is checked
and retried, and every error caught goes to generation_log.txt for the data card.
Run after load_rules.py:  python scripts/generate_students.py [--out DIR] [--as-of YYYY-MM-DD]
"""

import argparse
import csv
import json
import math
import sys
from datetime import date
from pathlib import Path
from string import Template
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # lets `python scripts/...` import app

from app import config, db, llm, precedence  # noqa: E402
from app.schemas import (  # noqa: E402
    AttendanceRow, CourseRow, GeneratedAttendance, GeneratedMarks, GeneratedStudent,
    ResultRow, StudentProfile, StudentRow,
)

# Data layout (docs/data_card.md). These shape the data set; decision thresholds come from rules.
BATCHES = {2023: 7, 2024: 5}  # batch_year -> current_semester as of Oct 2026
COURSES = [  # (course_code, course_name, programme, semester, credits)
    ("CS401", "Design and Analysis of Algorithms", "B.Tech CSE", 4, 4), ("CS402", "Database Management Systems", "B.Tech CSE", 4, 3),
    ("CS501", "Operating Systems", "B.Tech CSE", 5, 4), ("CS502", "Computer Networks", "B.Tech CSE", 5, 3),
    ("CS601", "Compiler Design", "B.Tech CSE", 6, 4), ("CS602", "Machine Learning", "B.Tech CSE", 6, 3),
    ("CS701", "Distributed Systems", "B.Tech CSE", 7, 4), ("CS702", "Information Security", "B.Tech CSE", 7, 3),
    ("EC401", "Analog Circuits", "B.Tech ECE", 4, 4), ("EC402", "Signals and Systems", "B.Tech ECE", 4, 3),
    ("EC501", "Digital Communication", "B.Tech ECE", 5, 4), ("EC502", "Microprocessors", "B.Tech ECE", 5, 3),
    ("EC601", "VLSI Design", "B.Tech ECE", 6, 4), ("EC602", "Control Systems", "B.Tech ECE", 6, 3),
    ("EC701", "Wireless Communication", "B.Tech ECE", 7, 4), ("EC702", "Embedded Systems", "B.Tech ECE", 7, 3),
]
EDGE_CASES = {  # student_id -> (programme, batch_year, case); the validator checks each one is present
    "S1001": ("B.Tech CSE", 2023, "attendance_at_threshold"),
    "S1002": ("B.Tech CSE", 2023, "attendance_one_below"),
    "S1003": ("B.Tech ECE", 2024, "attendance_at_threshold"),
    "S1004": ("B.Tech CSE", 2024, "fail_just_below_pass"),
    "S1005": ("B.Tech ECE", 2023, "absent"),
    "S1006": ("B.Tech ECE", 2024, "detained"),
    "S1007": ("B.Tech CSE", 2023, "multiple_backlogs"),
    "S1008": ("B.Tech ECE", 2023, "cgpa_at_cutoff"),
    "S1009": ("B.Tech ECE", 2024, "cgpa_one_below"),
    "S1010": ("B.Tech CSE", 2024, "fail_then_supplementary_pass"),
}
NORMAL_GROUPS = [("B.Tech CSE", 2023, 4), ("B.Tech ECE", 2024, 4), ("B.Tech CSE", 2024, 6), ("B.Tech ECE", 2023, 6)]
FIRST_NORMAL_ID = 1011
CLASSES_HELD = 40  # preferred; another value in HELD_RANGE is used if 40 cannot hit the threshold exactly
HELD_RANGE = range(30, 61)
MAX_INTERNAL, MAX_EXTERNAL = 40, 60
MAX_MARKS = MAX_INTERNAL + MAX_EXTERNAL
REGULAR_SESSION, SUPPLEMENTARY_SESSION = "2026-MAY", "2026-JUL"
PASS_MARGIN = 20  # marks above the pass mark for a comfortable pass
CGPA_MARGIN = 0.5  # S1004 sits this far above the placement cut-off
CGPA_STEP = 0.01  # CGPA is stored with 2 decimals, so "one below" is 0.01 lower
NO_EXAM_INTERNAL = MAX_INTERNAL // 2  # internal marks earned before an ABSENT or DETAINED exam
CGPA_MIN, CGPA_MAX, ATTENDANCE_MIN_PCT = 5.0, 9.8, 60  # ranges for LLM-filled values
MAX_LLM_ATTEMPTS = 3  # each attempt is a chat_json call, which itself retries invalid JSON once
LOG_FILE = "generation_log.txt"

ThresholdFn = Callable[[str, StudentProfile], float]  # (parameter, student) -> value in force


def courses_for(programme: str, semester: int) -> list[str]:
    return [code for code, _name, prog, sem, _credits in COURSES if prog == programme and sem == semester]


def plan_students() -> list[dict]:
    """Edge-case students first (fixed IDs), then the normal students."""
    students = [{"student_id": sid, "programme": p, "batch_year": b, "case": case}
                for sid, (p, b, case) in EDGE_CASES.items()]
    next_id = FIRST_NORMAL_ID
    for programme, batch_year, count in NORMAL_GROUPS:
        for _ in range(count):
            students.append({"student_id": f"S{next_id}", "programme": programme, "batch_year": batch_year, "case": None})
            next_id += 1
    return students


def split_marks(total: int) -> tuple[int, int]:
    """Splits a total into (internal, external) in proportion to their maximums."""
    internal = round(total * MAX_INTERNAL / MAX_MARKS)
    return internal, total - internal


def classes_for_threshold(attendance_pct: float) -> tuple[int, int]:
    """(held, attended) where attended / held is exactly the threshold."""
    for held in [CLASSES_HELD, *HELD_RANGE]:
        attended = held * attendance_pct / 100
        if math.isclose(attended, round(attended)):
            return held, round(attended)
    raise SystemExit(f"No classes_held in {HELD_RANGE} hits {attendance_pct}% exactly; widen HELD_RANGE")


def edge_fixed(case: str | None, current: list[str], previous: list[str], profile: StudentProfile,
               threshold: ThresholdFn, passing: int) -> dict:
    """The values code fixes for one student (edge-case table in docs/data_card.md)."""
    fixed: dict = {"held": CLASSES_HELD, "attendance": {}, "results": {}, "override": {}, "supplementary": None}
    if case is None:
        return fixed
    if case in ("attendance_at_threshold", "attendance_one_below"):
        held, at = classes_for_threshold(threshold("min_attendance_pct", profile))
        fixed["held"] = held
        fixed["attendance"][current[0]] = at if case == "attendance_at_threshold" else at - 1
        return fixed
    # Every other case depends on results, so all previous-semester marks are fixed to keep it exact.
    fixed["results"] = {code: split_marks(min(MAX_MARKS, passing + PASS_MARGIN)) for code in previous}
    fail = split_marks(passing - 1)
    if case in ("fail_just_below_pass", "multiple_backlogs"):
        extra = 1 if case == "fail_just_below_pass" else 2
        fails = int(threshold("placement_max_backlogs", profile)) + extra
        if fails > len(previous):
            raise SystemExit(f"{profile.student_id} needs {fails} FAILs; add earlier-semester results to the plan")
        fixed["results"].update({code: fail for code in previous[:fails]})
        if case == "fail_just_below_pass":
            fixed["cgpa"] = round(threshold("placement_min_cgpa", profile) + CGPA_MARGIN, 2)
    elif case in ("absent", "detained"):
        fixed["results"][previous[0]] = (NO_EXAM_INTERNAL, 0)
        fixed["override"][previous[0]] = case.upper()
        if case == "detained":
            fixed["attendance"][current[0]] = CLASSES_HELD // 2  # far below any attendance minimum
    elif case in ("cgpa_at_cutoff", "cgpa_one_below"):
        cutoff = threshold("placement_min_cgpa", profile)
        fixed["cgpa"] = round(cutoff if case == "cgpa_at_cutoff" else cutoff - CGPA_STEP, 2)
    elif case == "fail_then_supplementary_pass":
        fixed["results"][previous[1]] = fail
        fixed["supplementary"] = previous[1]
    return fixed


def build_prompts(student: dict, current: list[str], previous: list[str], fixed: dict) -> tuple[str, str]:
    """Fills the verbatim prompt templates in data/prompts/."""
    names = {code: name for code, name, *_ in COURSES}
    system = Template((config.PROMPTS_DIR / "student_system_prompt.txt").read_text(encoding="utf-8")).substitute(
        cgpa_min=CGPA_MIN, cgpa_max=CGPA_MAX, attendance_min_pct=ATTENDANCE_MIN_PCT,
        max_internal=MAX_INTERNAL, max_external=MAX_EXTERNAL)
    shown = {"attendance": fixed["attendance"],
             "results": {c: {"internal_marks": i, "external_marks": e} for c, (i, e) in fixed["results"].items()}}
    fill_in = ["full_name"] + ([] if "cgpa" in fixed else ["cgpa"])
    fill_in += [f"classes_attended for {c}" for c in current if c not in fixed["attendance"]]
    fill_in += [f"internal_marks and external_marks for {c}" for c in previous if c not in fixed["results"]]
    if "cgpa" in fixed:
        shown["cgpa"] = fixed["cgpa"]
    user = Template((config.PROMPTS_DIR / "student_user_prompt.txt").read_text(encoding="utf-8")).substitute(
        student_id=student["student_id"], programme=student["programme"], batch_year=student["batch_year"],
        current_semester=BATCHES[student["batch_year"]],
        attendance_courses="\n".join(f"- {c} {names[c]}: classes_held {fixed['held']}" for c in current),
        result_courses="\n".join(f"- {c} {names[c]}" for c in previous),
        fixed_values=json.dumps(shown), fill_in=", ".join(fill_in))
    return system, user


def mock_reply(student: dict, current: list[str], previous: list[str], fixed: dict) -> GeneratedStudent:
    """Stand-in reply for MOCK_LLM=true, so the pipeline runs without Ollama."""
    default_marks = split_marks(MAX_MARKS * 3 // 4)
    marks = {c: fixed["results"].get(c, default_marks) for c in previous}
    return GeneratedStudent(
        student_id=student["student_id"], full_name=f"Mock {student['student_id']}",
        cgpa=fixed.get("cgpa", (CGPA_MIN + CGPA_MAX) / 2),
        attendance=[GeneratedAttendance(course_code=c, classes_held=fixed["held"],
                                        classes_attended=fixed["attendance"].get(c, fixed["held"])) for c in current],
        results=[GeneratedMarks(course_code=c, internal_marks=marks[c][0], external_marks=marks[c][1]) for c in previous])


def llm_problems(reply: GeneratedStudent, student: dict, current: list[str], previous: list[str], fixed: dict) -> list[str]:
    """Everything wrong with an LLM reply. Fixed values are skipped: code overwrites them anyway."""
    problems = []
    if reply.student_id != student["student_id"]:
        problems.append(f"student_id {reply.student_id!r} instead of {student['student_id']}")
    if len(reply.full_name.split()) < 2:
        problems.append(f"full_name {reply.full_name!r} is not a first and last name")
    if "cgpa" not in fixed and not CGPA_MIN <= reply.cgpa <= CGPA_MAX:
        problems.append(f"cgpa {reply.cgpa} outside {CGPA_MIN}-{CGPA_MAX}")
    attendance = {a.course_code: a.classes_attended for a in reply.attendance}
    if sorted(attendance) != sorted(current):
        problems.append(f"attendance courses {sorted(attendance)} instead of {current}")
    low = fixed["held"] * ATTENDANCE_MIN_PCT / 100
    problems += [f"classes_attended {n} for {c} outside {low:g}-{fixed['held']}" for c, n in attendance.items()
                 if c not in fixed["attendance"] and not low <= n <= fixed["held"]]
    marks = {m.course_code: (m.internal_marks, m.external_marks) for m in reply.results}
    if sorted(marks) != sorted(previous):
        problems.append(f"result courses {sorted(marks)} instead of {previous}")
    problems += [f"marks {i}+{e} for {c} outside 0-{MAX_INTERNAL} / 0-{MAX_EXTERNAL}" for c, (i, e) in marks.items()
                 if c not in fixed["results"] and not (0 <= i <= MAX_INTERNAL and 0 <= e <= MAX_EXTERNAL)]
    return problems


def ask_llm(student: dict, current: list[str], previous: list[str], fixed: dict, log: list[str], usage: dict) -> GeneratedStudent:
    """Asks the LLM until a reply passes every check; logs each error caught."""
    system, user = build_prompts(student, current, previous, fixed)
    mock = mock_reply(student, current, previous, fixed)
    sid = student["student_id"]
    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        reply, call_usage = llm.chat_json(system, user, GeneratedStudent, mock, temperature=config.GENERATOR_TEMPERATURE)
        usage["calls"] += call_usage.calls
        usage["tokens"] += call_usage.tokens
        if reply is None:
            log.append(f"{sid} attempt {attempt}: invalid JSON twice in one chat_json call")
            continue
        problems = llm_problems(reply, student, current, previous, fixed)
        log += [f"{sid} attempt {attempt}: {p}" for p in problems]
        if not problems:
            return reply
    raise SystemExit(f"{sid}: no valid LLM reply after {MAX_LLM_ATTEMPTS} attempts; see {LOG_FILE}")


def build_rows(student: dict, current: list[str], previous: list[str], fixed: dict, reply: GeneratedStudent,
               passing: int, log: list[str]) -> tuple[StudentRow, list[AttendanceRow], list[ResultRow]]:
    """Merges fixed values over the LLM reply; total, result and backlogs are always computed here."""
    sid = student["student_id"]
    attendance = {a.course_code: a.classes_attended for a in reply.attendance}
    marks = {m.course_code: (m.internal_marks, m.external_marks) for m in reply.results}
    for code, value in fixed["attendance"].items():
        if attendance[code] != value:
            log.append(f"{sid}: LLM changed fixed classes_attended for {code} ({attendance[code]}); kept {value}")
    for code, value in fixed["results"].items():
        if marks[code] != value:
            log.append(f"{sid}: LLM changed fixed marks for {code} ({marks[code]}); kept {value}")
    if "cgpa" in fixed and reply.cgpa != fixed["cgpa"]:
        log.append(f"{sid}: LLM changed fixed cgpa ({reply.cgpa}); kept {fixed['cgpa']}")
    attendance.update(fixed["attendance"])
    marks.update(fixed["results"])

    def result_row(code: str, internal: int, external: int, session: str, exam_type: str) -> ResultRow:
        total = internal + external
        result = fixed["override"].get(code) if exam_type == "REGULAR" else None
        return ResultRow(student_id=sid, course_code=code, exam_session=session, exam_type=exam_type,
                         internal_marks=internal, external_marks=external, total_marks=total, max_marks=MAX_MARKS,
                         result=result or ("PASS" if total >= passing else "FAIL"))

    results = [result_row(c, *marks[c], REGULAR_SESSION, "REGULAR") for c in previous]
    if fixed["supplementary"]:
        results.append(result_row(fixed["supplementary"], *split_marks(min(MAX_MARKS, passing + PASS_MARGIN)),
                                  SUPPLEMENTARY_SESSION, "SUPPLEMENTARY"))
    latest = {r.course_code: r.result for r in results}  # rows are in session order, so the last one wins
    attendance_rows = [AttendanceRow(student_id=sid, course_code=c, classes_held=fixed["held"],
                                     classes_attended=attendance[c]) for c in current]
    student_row = StudentRow(student_id=sid, full_name=reply.full_name.strip(), programme=student["programme"],
                             batch_year=student["batch_year"], current_semester=BATCHES[student["batch_year"]],
                             cgpa=round(fixed.get("cgpa", reply.cgpa), 2),
                             active_backlogs=sum(1 for r in latest.values() if r != "PASS"))
    return student_row, attendance_rows, results


def write_csv(path: Path, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(type(rows[0]).model_fields))
        writer.writeheader()
        writer.writerows(row.model_dump() for row in rows)


def generate(threshold: ThresholdFn, out_dir: Path) -> dict:
    """Builds all four Annex C CSVs plus the generation log in out_dir. Returns a short summary."""
    log: list[str] = []
    usage = {"calls": 0, "tokens": 0}
    students, attendance, results = [], [], []
    for student in plan_students():
        semester = BATCHES[student["batch_year"]]
        current, previous = courses_for(student["programme"], semester), courses_for(student["programme"], semester - 1)
        # cgpa and backlogs are not known yet; precedence only needs programme and batch for its scope check.
        profile = StudentProfile(student_id=student["student_id"], programme=student["programme"],
                                 batch_year=student["batch_year"], current_semester=semester, cgpa=0, active_backlogs=0)
        passing = math.ceil(threshold("pass_mark_pct", profile) * MAX_MARKS / 100)
        fixed = edge_fixed(student["case"], current, previous, profile, threshold, passing)
        reply = ask_llm(student, current, previous, fixed, log, usage)
        student_row, attendance_rows, result_rows = build_rows(student, current, previous, fixed, reply, passing, log)
        students.append(student_row)
        attendance += attendance_rows
        results += result_rows
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "students.csv", students)
    write_csv(out_dir / "courses.csv", [CourseRow(course_code=c, course_name=n, programme=p, semester=s, credits=cr)
                                        for c, n, p, s, cr in COURSES])
    write_csv(out_dir / "attendance.csv", attendance)
    write_csv(out_dir / "results.csv", results)
    summary = {"students": len(students), "llm_calls": usage["calls"], "tokens": usage["tokens"],
               "errors_logged": len(log), "model": llm.model_name(), "temperature": config.GENERATOR_TEMPERATURE}
    (out_dir / LOG_FILE).write_text(json.dumps(summary) + "\n" + "\n".join(log) + "\n", encoding="utf-8")
    return summary


def registry_threshold(parameter: str, profile: StudentProfile, as_of_date: str) -> float:
    """The value in force for this student, chosen by Person A's precedence resolver (spec D.5)."""
    resolution = precedence.resolve_rules(db.get_rules(parameter), db.get_sources(),
                                          date.fromisoformat(as_of_date), profile.model_dump())
    if resolution.status != "RESOLVED" or resolution.winner is None:
        raise SystemExit(f"{parameter} for {profile.student_id}: {resolution.status}. Load data/rules.csv first.")
    return float(resolution.winner.value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=config.STUDENTS_DIR)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="date the thresholds are resolved for")
    args = parser.parse_args()
    db.init_db()
    summary = generate(lambda parameter, profile: registry_threshold(parameter, profile, args.as_of), args.out)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
