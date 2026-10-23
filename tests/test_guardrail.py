"""
Tests for app/guardrail.py (spec D.3 node 2). Stub stage: checks the final
signature. The refusal tests (cross-student request, personal question with
no header) are added in step 5.
"""

from app import guardrail


def test_check_returns_message_or_none():
    outcome = guardrail.check("S1001", "What is the minimum attendance?", "policy_fact")
    assert outcome is None or isinstance(outcome, str)
