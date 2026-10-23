"""
Tests for app/tools.py (spec D.7). Stub stage: checks that every tool exists
with its final signature and returns a ToolResult. Behaviour tests on the
edge-case students (exactly-at-threshold, one-below) are added in step 5.
"""

from app import tools
from app.schemas import ToolResult


def test_every_tool_returns_a_tool_result():
    results = [
        tools.get_student_profile("S1001"),
        tools.get_attendance("S1001", "CS701"),
        tools.get_results("S1001"),
        tools.check_exam_eligibility("S1001", "CS701", "2026-10-23"),
        tools.check_supplementary_eligibility("S1004", "CS401", "2026-10-23"),
        tools.check_placement_eligibility("S1004", "2026-10-23", assume_passed=["CS401"]),
    ]
    for result in results:
        assert isinstance(result, ToolResult)


def test_helpers_exist():
    assert tools.get_student("S1001") is None or tools.get_student("S1001").student_id == "S1001"
    assert isinstance(tools.list_courses("S1001"), list)
