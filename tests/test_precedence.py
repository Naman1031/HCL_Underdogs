"""
Unit tests for the Annex A precedence policy (PROJECT_SPEC D.5).

The first test is the brief's own worked example (Annex A.3) and must pass
exactly. The rest cover one Annex A.2 step each, plus upcoming documents,
untrusted level-5 sources and an unresolved conflict.
"""

from datetime import date

from app.precedence import applicability, resolve_rules

AS_OF = date(2026, 10, 6)


def source(doc_id, level, effective_from, **extra):
    """Build a Source Register row (Annex B) with sensible defaults."""
    row = {
        "doc_id": doc_id,
        "authority_level": level,
        "effective_from": effective_from,
        "effective_to": "",
        "supersedes": "",
        "scope_programmes": "ALL",
        "scope_batches": "ALL",
    }
    row.update(extra)
    return row


def rule(rule_id, value, doc_id, section, effective_from, **extra):
    """Build a rule_registry row (Annex C) with sensible defaults."""
    row = {
        "rule_id": rule_id,
        "description": f"minimum attendance {value}%",
        "parameter": "min_attendance_pct",
        "operator": ">=",
        "value": value,
        "source_doc_id": doc_id,
        "source_section": section,
        "effective_from": effective_from,
        "effective_to": "",
        "scope_programmes": "ALL",
        "scope_batches": "ALL",
    }
    row.update(extra)
    return row


# --------------------------------------------------------------------------
# The brief's worked example, Annex A.3
# --------------------------------------------------------------------------


def test_annex_a3_worked_example():
    """Circular supersedes the regulation clause -> 80% by step 2, FAQ noted."""
    sources = [
        source("ACAD-REG-2024", 1, "2024-07-01"),
        source("ACAD-2026-08", 2, "2026-08-01", supersedes="ACAD-REG-2024#7.2"),
        source("DEPT-FAQ", 4, "2026-09-15"),
    ]
    rules = [
        rule("ATT-MIN-01", "75", "ACAD-REG-2024", "7.2", "2024-07-01"),
        rule("ATT-MIN-02", "80", "ACAD-2026-08", "1", "2026-08-01"),
        rule("ATT-MIN-03", "65", "DEPT-FAQ", "3", "2026-09-15"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "RESOLVED"
    assert result.winner.value == "80"
    assert result.winner.source_doc_id == "ACAD-2026-08"
    assert result.step_used == 2
    assert result.decision_text == "ACAD-2026-08 supersedes ACAD-REG-2024#7.2 (step 2)"

    # The regulation lost at step 2 and the FAQ at step 3; both are recorded.
    assert {r.rule_id for r in result.overridden} == {"ATT-MIN-01", "ATT-MIN-03"}


# --------------------------------------------------------------------------
# Step 1: applicability
# --------------------------------------------------------------------------


def test_applicability_current_upcoming_expired():
    assert applicability(source("A", 1, "2024-01-01"), AS_OF) == "current"
    assert applicability(source("B", 1, "2027-01-01"), AS_OF) == "upcoming"
    assert applicability(
        source("C", 1, "2020-01-01", effective_to="2024-01-01"), AS_OF
    ) == "expired"


def test_applicability_scope_by_programme_and_batch():
    student = {"programme": "B.Tech CSE", "batch_year": 2023}

    assert applicability(
        source("A", 1, "2024-01-01", scope_programmes="B.Tech CSE"), AS_OF, student
    ) == "current"
    assert applicability(
        source("B", 1, "2024-01-01", scope_programmes="B.Tech ECE"), AS_OF, student
    ) == "out_of_scope"
    assert applicability(
        source("C", 1, "2024-01-01", scope_batches="2023+"), AS_OF, student
    ) == "current"
    assert applicability(
        source("D", 1, "2024-01-01", scope_batches="2024+"), AS_OF, student
    ) == "out_of_scope"


def test_general_question_only_matches_all_scope():
    """With no student we cannot verify scope, so only ALL may be applied."""
    narrow = source("A", 1, "2024-01-01", scope_programmes="B.Tech CSE")
    assert applicability(narrow, AS_OF, None) == "out_of_scope"


def test_upcoming_document_is_not_used():
    sources = [
        source("ACAD-REG-2024", 1, "2024-07-01"),
        source("FUTURE-NOTICE", 2, "2027-01-01"),
    ]
    rules = [
        rule("ATT-MIN-01", "75", "ACAD-REG-2024", "7.2", "2024-07-01"),
        rule("ATT-MIN-09", "85", "FUTURE-NOTICE", "1", "2027-01-01"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "RESOLVED"
    assert result.winner.value == "75"


# --------------------------------------------------------------------------
# Step 3: authority beats date
# --------------------------------------------------------------------------


def test_higher_authority_wins_even_when_older():
    sources = [
        source("ACAD-REG-2024", 1, "2024-07-01"),
        source("DEPT-NOTICE", 3, "2026-09-01"),
    ]
    rules = [
        rule("ATT-MIN-01", "75", "ACAD-REG-2024", "7.2", "2024-07-01"),
        rule("ATT-MIN-04", "60", "DEPT-NOTICE", "2", "2026-09-01"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "RESOLVED"
    assert result.winner.value == "75"
    assert result.step_used == 3


# --------------------------------------------------------------------------
# Step 4: recency between equals
# --------------------------------------------------------------------------


def test_recency_breaks_tie_at_same_authority():
    sources = [
        source("CIRC-2025", 2, "2025-01-01"),
        source("CIRC-2026", 2, "2026-01-01"),
    ]
    rules = [
        rule("ATT-MIN-05", "70", "CIRC-2025", "1", "2025-01-01"),
        rule("ATT-MIN-06", "78", "CIRC-2026", "1", "2026-01-01"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "RESOLVED"
    assert result.winner.value == "78"
    assert result.step_used == 4


# --------------------------------------------------------------------------
# Step 5 and the untrusted level
# --------------------------------------------------------------------------


def test_same_authority_same_date_different_values_is_a_conflict():
    sources = [
        source("CIRC-A", 2, "2026-01-01"),
        source("CIRC-B", 2, "2026-01-01"),
    ]
    rules = [
        rule("ATT-MIN-07", "70", "CIRC-A", "1", "2026-01-01"),
        rule("ATT-MIN-08", "80", "CIRC-B", "1", "2026-01-01"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "CONFLICT"
    assert result.step_used == 5
    assert {r.value for r in result.conflicts} == {"70", "80"}


def test_level_5_can_never_win():
    sources = [source("FORUM-POST", 5, "2026-09-01")]
    rules = [rule("ATT-MIN-99", "50", "FORUM-POST", "1", "2026-09-01")]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.status == "NO_RULE"


def test_no_applicable_rule_returns_no_rule():
    """Callers turn NO_RULE into RULE_UNCERTAIN rather than guessing."""
    result = resolve_rules([], [], AS_OF)
    assert result.status == "NO_RULE"


def test_step_1_filtering_does_not_claim_to_be_the_deciding_step():
    """
    Regression: dropping a not-yet-effective rule at step 1 must not make the
    audit sentence read "(step 1)" when supersession is what actually decided.
    """
    sources = [
        source("ACAD-ORD-2022", 1, "2022-07-01"),
        source("ACAD-CIRC-2026-08", 2, "2026-08-01",
               supersedes="ACAD-ORD-2022#R.1(B).22"),
        source("DTU-NOTICE-2026-11", 3, "2026-11-15"),  # upcoming, filtered at step 1
    ]
    rules = [
        rule("ATT-MIN-01", "75", "ACAD-ORD-2022", "R.1(B).22", "2022-07-01"),
        rule("ATT-MIN-02", "80", "ACAD-CIRC-2026-08", "2.1", "2026-08-01"),
        rule("ATT-MIN-03", "85", "DTU-NOTICE-2026-11", "1", "2026-11-15"),
    ]

    result = resolve_rules(rules, sources, AS_OF)

    assert result.winner.value == "80"
    assert result.step_used == 2
    assert result.decision_text == (
        "ACAD-CIRC-2026-08 supersedes ACAD-ORD-2022#R.1(B).22 (step 2)"
    )
