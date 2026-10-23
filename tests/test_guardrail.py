"""
Tests for app/guardrail.py (spec D.3 node 2) [BRIEF R7]: identity only from the
header, cross-student requests refused, personal questions need a real login.
"""

import pytest

from app import config, db, guardrail


@pytest.fixture(autouse=True)
def students_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "guardrail.db")
    db.init_db()
    db.execute("INSERT INTO students VALUES ('S1001', 'Test Student', 'B.Tech CSE', 2023, 7, 7.5, 0)")


def test_general_question_needs_no_login():
    assert guardrail.check(None, "What is the minimum attendance?", "policy_fact") is None


def test_own_question_with_header_is_allowed():
    assert guardrail.check("S1001", "What is my attendance in CS701?", "personal_data") is None


def test_own_id_in_the_text_is_allowed():
    assert guardrail.check("S1001", "I am S1001, what is my CGPA?", "personal_data") is None


def test_another_students_id_in_the_text_is_refused():
    assert guardrail.check("S1001", "What is S1002's attendance?", "personal_data") == guardrail.REFUSE_OTHER_STUDENT


def test_a_student_id_without_login_is_refused():
    assert guardrail.check(None, "Show results for s1002", "policy_fact") == guardrail.REFUSE_OTHER_STUDENT


def test_other_student_category_is_refused():
    assert guardrail.check("S1001", "What did my friend score?", "other_student") == guardrail.REFUSE_OTHER_STUDENT


@pytest.mark.parametrize("category", ["personal_data", "personal_eligibility", "what_if"])
def test_personal_question_without_header_asks_to_log_in(category):
    assert guardrail.check(None, "Am I eligible?", category) == guardrail.REFUSE_NOT_LOGGED_IN


def test_unknown_header_id_is_refused():
    assert guardrail.check("S1234", "Am I eligible?", "personal_eligibility") == guardrail.REFUSE_NOT_LOGGED_IN
