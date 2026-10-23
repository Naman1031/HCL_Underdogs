"""
Validates a folder of Annex C student CSVs (spec F.6) [BRIEF Section 4.2].
Generic checks (any folder, including the judges'): columns and types, ID formats,
duplicates, attended <= held, marks, total = internal + external, result vs the
pass mark from rule_registry, and programmes matching between students and courses.
Our own data also gets: no reserved IDs, minimum counts and every planned edge case.
Usage: python scripts/validate_students.py [--dir DIR] [--generic] [--as-of YYYY-MM-DD]
"""

import argparse
import csv
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # lets `python scripts/...` import app

from pydantic import ValidationError  # noqa: E402

from app import config, db, precedence  # noqa: E402
from app.schemas import AttendanceRow, CourseRow, ResultRow, StudentRow  # noqa: E402
from scripts.generate_students import CGPA_STEP, EDGE_CASES  # noqa: E402

FILES = {"students.csv": StudentRow, "courses.csv": CourseRow, "attendance.csv": AttendanceRow, "results.csv": ResultRow}
RESERVED_STUDENT_PREFIX, RESERVED_COURSE_PREFIX = "S9", "JDG"  # S9000-S9999 and JDG* belong to the judges
MIN_STUDENTS, MIN_PROGRAMMES, MIN_BATCHES, MIN_COURSES = 30, 2, 2, 6  # spec F.6 minimums
REPORT_FILE = "validation_report.txt"

Threshold = Callable[[str, dict], float | None]  # (parameter, {programme, batch_year}) -> value or None


def read_rows(folder: Path) -> tuple[dict[str, list], list[str]]:
    """Parses each CSV that exists into its Pydantic row model. Missing files are skipped."""
    rows: dict[str, list] = {}
    errors: list[str] = []
    for name, model in FILES.items():
        path = folder / name
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig: CSVs saved by Excel start with a BOM
            reader = csv.DictReader(f)
            missing = set(model.model_fields) - set(reader.fieldnames or [])
            if missing:
                errors.append(f"{name}: missing columns {sorted(missing)}")
                continue
            parsed = []
            for line, raw in enumerate(reader, start=2):  # line 1 is the header
                try:
                    parsed.append(model(**{k: (v or "").strip() for k, v in raw.items() if k in model.model_fields}))
                except ValidationError as exc:
                    errors += [f"{name} line {line}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            rows[name] = parsed
    return rows, errors


def registry_threshold(as_of: date) -> Threshold:
    """Looks thresholds up through Person A's precedence resolver, once per programme and batch."""
    cache: dict[tuple, float | None] = {}

    def lookup(parameter: str, student: dict) -> float | None:
        key = (parameter, student["programme"], student["batch_year"])
        if key not in cache:
            resolution = precedence.resolve_rules(db.get_rules(parameter), db.get_sources(), as_of, student)
            ok = resolution.status == "RESOLVED" and resolution.winner is not None
            cache[key] = float(resolution.winner.value) if ok else None
        return cache[key]
    return lookup


def duplicates(keys: list) -> list:
    return [key for key, count in Counter(keys).items() if count > 1]


def check_rows(rows: dict[str, list], threshold: Threshold, known_students: dict, known_courses: dict) -> tuple[list[str], list[str]]:
    """Generic checks. known_* are rows already in SQLite, so a folder may hold only some files."""
    errors, notes = [], []
    students, courses = rows.get("students.csv", []), rows.get("courses.csv", [])
    attendance, results = rows.get("attendance.csv", []), rows.get("results.csv", [])
    student_info = {**known_students, **{s.student_id: {"programme": s.programme, "batch_year": s.batch_year} for s in students}}
    course_programme = {**known_courses, **{c.course_code: c.programme for c in courses}}

    errors += [f"students.csv: duplicate student_id {k}" for k in duplicates([s.student_id for s in students])]
    errors += [f"courses.csv: duplicate course_code {k}" for k in duplicates([c.course_code for c in courses])]
    errors += [f"attendance.csv: duplicate row {k}" for k in duplicates([(a.student_id, a.course_code) for a in attendance])]
    errors += [f"results.csv: duplicate row {k}" for k in duplicates(
        [(r.student_id, r.course_code, r.exam_session, r.exam_type) for r in results])]
    programmes = set(course_programme.values())
    errors += [f"students.csv: {s.student_id} programme {s.programme!r} has no courses" for s in students if s.programme not in programmes]

    for name, row in [("attendance.csv", a) for a in attendance] + [("results.csv", r) for r in results]:
        where = f"{name} {row.student_id}/{row.course_code}"
        if row.student_id not in student_info:
            errors.append(f"{where}: unknown student_id")
        elif row.course_code not in course_programme:
            errors.append(f"{where}: unknown course_code")
        elif course_programme[row.course_code] != student_info[row.student_id]["programme"]:
            errors.append(f"{where}: course belongs to {course_programme[row.course_code]!r}, not the student's programme")

    errors += [f"attendance.csv {a.student_id}/{a.course_code}: attended {a.classes_attended} > held {a.classes_held}"
               for a in attendance if a.classes_attended > a.classes_held]

    unchecked = set()
    for r in results:
        where = f"results.csv {r.student_id}/{r.course_code}/{r.exam_session}"
        if min(r.internal_marks, r.external_marks) < 0 or r.max_marks <= 0 or r.total_marks > r.max_marks:
            errors.append(f"{where}: marks out of range ({r.internal_marks}+{r.external_marks}, max {r.max_marks})")
        if r.total_marks != r.internal_marks + r.external_marks:
            errors.append(f"{where}: total {r.total_marks} != internal {r.internal_marks} + external {r.external_marks}")
        if r.result in ("ABSENT", "DETAINED") or r.student_id not in student_info:
            continue  # allowed exceptions to the pass-mark rule (spec F.6)
        pass_pct = threshold("pass_mark_pct", student_info[r.student_id])
        if pass_pct is None:
            unchecked.add(r.student_id)
            continue
        expected = "PASS" if r.total_marks >= math.ceil(pass_pct * r.max_marks / 100) else "FAIL"
        if r.result != expected:
            errors.append(f"{where}: result {r.result} but total {r.total_marks}/{r.max_marks} means {expected} (pass mark {pass_pct:g}%)")
    if unchecked:
        notes.append(f"No pass_mark_pct rule resolved for {len(unchecked)} students; their result-vs-marks check was skipped")
    return errors, notes


def case_present(case: str, student: StudentRow, attendance: list, results: list, rule: Callable[[str], float]) -> bool:
    """True if the student's rows really carry this edge case (docs/data_card.md)."""
    if case in ("attendance_at_threshold", "attendance_one_below"):
        pct = rule("min_attendance_pct")
        if case == "attendance_at_threshold":
            return any(math.isclose(a.classes_attended * 100 / a.classes_held, pct) for a in attendance)
        return any(a.classes_attended * 100 / a.classes_held < pct <= (a.classes_attended + 1) * 100 / a.classes_held
                   for a in attendance)
    if case == "fail_just_below_pass":
        pct = rule("pass_mark_pct")
        return any(r.result == "FAIL" and r.total_marks == math.ceil(pct * r.max_marks / 100) - 1 for r in results)
    if case in ("absent", "detained"):
        return any(r.result == case.upper() for r in results)
    if case == "multiple_backlogs":
        return student.active_backlogs >= 2
    if case in ("cgpa_at_cutoff", "cgpa_one_below"):
        cutoff = rule("placement_min_cgpa")
        return math.isclose(student.cgpa, cutoff if case == "cgpa_at_cutoff" else round(cutoff - CGPA_STEP, 2))
    if case == "fail_then_supplementary_pass":
        failed = {r.course_code for r in results if r.exam_type == "REGULAR" and r.result == "FAIL"}
        return any(r.exam_type == "SUPPLEMENTARY" and r.result == "PASS" and r.course_code in failed for r in results)
    raise ValueError(f"unknown edge case {case}")


def check_ours(rows: dict[str, list], threshold: Threshold) -> list[str]:
    """Checks that only apply to our generated data: reserved IDs, minimum counts, edge-case plan."""
    errors = []
    students, courses = rows.get("students.csv", []), rows.get("courses.csv", [])
    ids = {s.student_id for s in students} | {r.student_id for name in ("attendance.csv", "results.csv") for r in rows.get(name, [])}
    codes = {c.course_code for c in courses}
    errors += [f"reserved student_id {i} (S9000-S9999 belong to the judges)" for i in sorted(ids) if i.startswith(RESERVED_STUDENT_PREFIX)]
    errors += [f"reserved course_code {c} (JDG* belongs to the judges)" for c in sorted(codes) if c.startswith(RESERVED_COURSE_PREFIX)]
    counts = {"students": (len(students), MIN_STUDENTS), "programmes": (len({s.programme for s in students}), MIN_PROGRAMMES),
              "batches": (len({s.batch_year for s in students}), MIN_BATCHES), "courses": (len(courses), MIN_COURSES)}
    errors += [f"only {n} {what}, minimum is {minimum}" for what, (n, minimum) in counts.items() if n < minimum]

    by_id = {s.student_id: s for s in students}
    for sid, (programme, batch_year, case) in EDGE_CASES.items():
        student = by_id.get(sid)
        if student is None or (student.programme, student.batch_year) != (programme, batch_year):
            errors.append(f"edge case {case}: {sid} missing or not in {programme} / {batch_year}")
            continue
        info = {"programme": programme, "batch_year": batch_year}

        def rule(parameter: str) -> float:
            value = threshold(parameter, info)
            if value is None:
                raise LookupError(parameter)
            return value
        attendance = [a for a in rows.get("attendance.csv", []) if a.student_id == sid]
        results = [r for r in rows.get("results.csv", []) if r.student_id == sid]
        try:
            if not case_present(case, student, attendance, results, rule):
                errors.append(f"edge case {case}: not present for {sid}")
        except LookupError as missing:
            errors.append(f"edge case {case}: cannot check {sid}, no rule resolved for {missing}")
    return errors


def validate(folder: Path, ours: bool, as_of: date, known_students: dict | None = None,
             known_courses: dict | None = None) -> tuple[dict[str, list], list[str], list[str]]:
    """Returns (parsed rows, errors, report lines). No errors means the folder is safe to load."""
    threshold = registry_threshold(as_of)
    rows, errors = read_rows(folder)
    row_errors, notes = check_rows(rows, threshold, known_students or {}, known_courses or {})
    errors += row_errors + (check_ours(rows, threshold) if ours else [])
    students, results = rows.get("students.csv", []), rows.get("results.csv", [])
    report = [f"Validation of {folder} ({'our data: all checks' if ours else 'generic checks'}), rules as of {as_of}",
              f"RESULT: {'PASS' if not errors else 'FAIL'} ({len(errors)} errors)", "",
              "Rows: " + ", ".join(f"{name} {len(rows[name])}" if name in rows else f"{name} not present" for name in FILES),
              "Students per programme / batch: " + ", ".join(
                  f"{p} {b}: {n}" for (p, b), n in sorted(Counter((s.programme, s.batch_year) for s in students).items())),
              "Results by outcome: " + ", ".join(f"{k} {n}" for k, n in sorted(Counter(r.result for r in results).items())),
              *notes, "", *(["Errors:"] + [f"- {e}" for e in errors] if errors else [])]
    return rows, errors, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=config.STUDENTS_DIR)
    parser.add_argument("--generic", action="store_true", help="skip checks that only apply to our own generated data")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="date the pass mark and other rules are resolved for")
    args = parser.parse_args()
    db.init_db()
    _rows, errors, report = validate(args.dir, not args.generic, date.fromisoformat(args.as_of))
    (args.dir / REPORT_FILE).write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
