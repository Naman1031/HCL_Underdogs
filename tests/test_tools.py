"""
Tests for app/tools.py (spec D.7) on the edge-case students from
docs/data_card.md: exactly-at-threshold is ELIGIBLE, one-below is NOT_ELIGIBLE,
FAIL/ABSENT may take the supplementary but DETAINED may not, and placement
what-if clears a backlog. Thresholds come from rule_registry, as in production.
"""

import pytest

from app import config, db, tools

AS_OF = "2026-10-23"


@pytest.fixture(autouse=True)
def tools_db(tmp_path, monkeypatch):
    """A fresh SQLite file per test with a small registry and edge-case students."""
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "tools.db")
    db.init_db()
    db.execute("INSERT INTO sources (doc_id, title, issuer, authority_level, doc_type, version, effective_from, "
               "scope_programmes, scope_batches, synthetic) VALUES ('REG', 'Regulations', 'Registrar', 1, "
               "'regulation', '1', '2022-07-01', 'ALL', 'ALL', 'N')")
    rules = [("ATT", "min_attendance_pct", ">=", "75"), ("SUPP", "supplementary_allowed_results", "in", "FAIL;ABSENT"),
             ("CGPA", "placement_min_cgpa", ">=", "6.0"), ("BACK", "placement_max_backlogs", "<=", "0")]
    db.execute_many("INSERT INTO rule_registry VALUES (?, 'test rule', ?, ?, ?, 'ALL', 'ALL', '2022-07-01', NULL, "
                    "'REG', '1', 'manual')", rules)
    db.execute_many("INSERT INTO courses VALUES (?, ?, 'B.Tech CSE', ?, 4)",
                    [("CS401", "Algorithms", 4), ("CS402", "Databases", 4), ("CS701", "Distributed Systems", 7)])
    students = [("S1001", 7.5, 0), ("S1002", 7.5, 0), ("S1004", 6.5, 1), ("S1005", 7.0, 1),
                ("S1006", 7.0, 1), ("S1008", 6.0, 0), ("S1009", 5.99, 0), ("S1010", 7.0, 0)]
    db.execute_many("INSERT INTO students VALUES (?, 'Test Student', 'B.Tech CSE', 2023, 7, ?, ?)", students)
    db.execute_many("INSERT INTO attendance VALUES (?, 'CS701', 40, ?)", [("S1001", 30), ("S1002", 29)])
    results = [("S1004", "CS401", "2026-MAY", "REGULAR", 16, 23, 39, "FAIL"),
               ("S1005", "CS401", "2026-MAY", "REGULAR", 20, 0, 20, "ABSENT"),
               ("S1006", "CS401", "2026-MAY", "REGULAR", 20, 0, 20, "DETAINED"),
               ("S1010", "CS402", "2026-MAY", "REGULAR", 16, 23, 39, "FAIL"),
               ("S1010", "CS402", "2026-JUL", "SUPPLEMENTARY", 24, 36, 60, "PASS")]
    db.execute_many("INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, 100, ?)", results)


def test_attendance_is_computed_to_two_decimals():
    out = tools.get_attendance("S1002", "CS701").output
    assert out == {"classes_held": 40, "classes_attended": 29, "attendance_pct": 72.5}


def test_attendance_exactly_at_threshold_is_eligible():
    result = tools.check_exam_eligibility("S1001", "CS701", AS_OF)
    assert result.output["result"] == "ELIGIBLE"
    assert result.output["attendance_pct"] == 75.0
    assert result.rule_ids == ["ATT"]


def test_attendance_one_class_below_is_not_eligible():
    assert tools.check_exam_eligibility("S1002", "CS701", AS_OF).output["result"] == "NOT_ELIGIBLE"


def test_missing_record_is_an_error_not_a_guess():
    result = tools.check_exam_eligibility("S1001", "CS401", AS_OF)
    assert result.status == "error"
    assert "error" in result.output


@pytest.mark.parametrize("student_id, expected", [("S1004", "ELIGIBLE"), ("S1005", "ELIGIBLE"),
                                                  ("S1006", "NOT_ELIGIBLE")])
def test_supplementary_is_open_to_fail_and_absent_but_not_detained(student_id, expected):
    result = tools.check_supplementary_eligibility(student_id, "CS401", AS_OF)
    assert result.output["result"] == expected
    assert result.rule_ids == ["SUPP"]


def test_placement_backlog_blocks_and_what_if_clears_it():
    before = tools.check_placement_eligibility("S1004", AS_OF)
    after = tools.check_placement_eligibility("S1004", AS_OF, assume_passed=["CS401"])
    assert before.output["result"] == "NOT_ELIGIBLE"
    assert after.output["result"] == "ELIGIBLE"
    assert after.output["backlogs"] == 0 and after.output["assumed_passed"] == ["CS401"]
    assert sorted(after.rule_ids) == ["BACK", "CGPA"]


def test_assuming_a_course_already_passed_changes_nothing():
    result = tools.check_placement_eligibility("S1010", AS_OF, assume_passed=["CS402"])
    assert result.output["assumed_passed"] == []  # CS402's latest result is already PASS


@pytest.mark.parametrize("student_id, expected", [("S1008", "ELIGIBLE"), ("S1009", "NOT_ELIGIBLE")])
def test_cgpa_exactly_at_cutoff_is_eligible_and_just_below_is_not(student_id, expected):
    assert tools.check_placement_eligibility(student_id, AS_OF).output["result"] == expected


def test_results_are_latest_session_first():
    rows = tools.get_results("S1010", "CS402").output["results"]
    assert [r["exam_session"] for r in rows] == ["2026-JUL", "2026-MAY"]
    assert rows[0]["result"] == "PASS"


def test_unknown_rule_gives_rule_uncertain_not_a_verdict():
    db.execute("DELETE FROM rule_registry WHERE parameter = 'min_attendance_pct'")
    assert tools.check_exam_eligibility("S1001", "CS701", AS_OF).output["result"] == "RULE_UNCERTAIN"


def test_lookups():
    assert tools.get_student("S9999") is None
    assert tools.get_student("S1001").programme == "B.Tech CSE"
    assert tools.list_courses("S1010") == [{"course_code": "CS402", "course_name": "Databases"}]
