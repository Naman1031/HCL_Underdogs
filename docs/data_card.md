# Data card: synthetic student data

Annex E of the brief. **Draft (step 1):** the edge-case plan and design decisions are final; counts, validation results and LLM errors are filled in after the generator runs.

## Purpose

Fictional students, courses, attendance and results for testing the assistant's personal-data tools (spec D.7) and guardrail. **No real student data.** IDs `S9000`–`S9999` and course codes starting with `JDG` are never used (reserved for judges).

## Generator

- Model: `qwen2.5:7b-instruct` via Ollama (`app/llm.py`), temperature 0.7, one call per student (about 30 calls). Final count: _TODO after run_.
- Prompts (verbatim, loaded from disk by the generator): [`data/prompts/student_system_prompt.txt`](../data/prompts/student_system_prompt.txt), [`data/prompts/student_user_prompt.txt`](../data/prompts/student_user_prompt.txt). Placeholders use Python `string.Template` (`$name`), so JSON braces need no escaping.
- **Code decides, the LLM fills in.** Code fixes `student_id`, programme, batch, semester, courses, `classes_held` and every edge-case value. The LLM only invents names, CGPA (normal students), `classes_attended` and internal/external marks for non-edge courses. Code then computes `total_marks`, `result` and `active_backlogs`, so they are always consistent.
- Each LLM reply is validated with Pydantic and retried on failure. Any fixed value the LLM changed is overwritten by code and logged.

## Design decisions

| Item | Value |
|---|---|
| Programmes | `B.Tech CSE`, `B.Tech ECE` |
| Batches | 2023 (current semester 7), 2024 (current semester 5), as of Oct 2026 |
| Students | 30: `S1001`–`S1030` |
| Courses | 16: 2 per semester (4, 5, 6, 7) per programme |
| Attendance rows | current-semester courses, `classes_held` = 40 (see below) |
| Result rows | previous-semester courses, session `2026-MAY`, `REGULAR`; one `SUPPLEMENTARY` in `2026-JUL` |
| Marks scheme | internal 0–40, external 0–60, max 100. _TODO: confirm against the DTU scheme from Person A_ |

### Courses

| Semester | B.Tech CSE | B.Tech ECE |
|---|---|---|
| 4 | CS401 Design and Analysis of Algorithms, CS402 Database Management Systems | EC401 Analog Circuits, EC402 Signals and Systems |
| 5 | CS501 Operating Systems, CS502 Computer Networks | EC501 Digital Communication, EC502 Microprocessors |
| 6 | CS601 Compiler Design, CS602 Machine Learning | EC601 VLSI Design, EC602 Control Systems |
| 7 | CS701 Distributed Systems, CS702 Information Security | EC701 Wireless Communication, EC702 Embedded Systems |

## Edge cases

Thresholds come from `rule_registry` (Person A's `data/rules.csv`). Until it exists they are **TODO**; the bracketed values are only examples.

- `T_ATT` = `min_attendance_pct` (e.g. 75)
- `PASS` = `pass_mark_pct` (e.g. 40)
- `CGPA_CUT` = `placement_min_cgpa` (e.g. 7.0)
- `MAX_BL` = `placement_max_backlogs` (e.g. 0)

How code derives the boundary numbers:
- **Attendance:** `held = 40`, `at = held × T_ATT / 100`. If `at` is not a whole number, code picks the smallest `held` in 30–60 that makes it one. One below = `at − 1` (e.g. 30/40 = 75.00%, 29/40 = 72.50%).
- **Marks:** just below the pass mark = `ceil(PASS × max / 100) − 1` (e.g. 39/100).
- **CGPA:** at the cut-off = `CGPA_CUT`, one below = `CGPA_CUT − 0.01`.
- **Backlogs:** `active_backlogs` = number of courses whose latest result is FAIL, ABSENT or DETAINED.

| ID | Programme / batch | Edge case | Exact values | Expected tool result |
|---|---|---|---|---|
| S1001 | CSE / 2023 | Attendance exactly at threshold | CS701: `at` / `held` | exam eligibility: ELIGIBLE |
| S1002 | CSE / 2023 | Attendance one class below | CS701: `at − 1` / `held` | exam eligibility: NOT_ELIGIBLE |
| S1003 | ECE / 2024 | Attendance exactly at threshold (other programme and batch, for scope) | EC501: `at` / `held` | exam eligibility: ELIGIBLE |
| S1004 | CSE / 2024 | FAIL just below pass mark (what-if demo) | CS401 total = `PASS − 1`, backlogs = `MAX_BL + 1`, CGPA = `CGPA_CUT + 0.5` | supplementary: ELIGIBLE; placement: NOT_ELIGIBLE, ELIGIBLE with `assume_passed=["CS401"]` |
| S1005 | ECE / 2023 | ABSENT | EC601 external = 0, total = internal, ABSENT | supplementary: ELIGIBLE (_TODO: confirm rule_) |
| S1006 | ECE / 2024 | DETAINED | EC401 DETAINED, external = 0; EC501 attendance `held / 2` | supplementary: NOT_ELIGIBLE (_TODO: confirm rule_) |
| S1007 | CSE / 2023 | Multiple backlogs | CS601 and CS602 FAIL, backlogs = `MAX_BL + 2` | placement: NOT_ELIGIBLE, still with one `assume_passed` |
| S1008 | ECE / 2023 | CGPA exactly at cut-off | CGPA = `CGPA_CUT`, backlogs = 0 | placement: ELIGIBLE |
| S1009 | ECE / 2024 | CGPA one below cut-off | CGPA = `CGPA_CUT − 0.01`, backlogs = 0 | placement: NOT_ELIGIBLE |
| S1010 | CSE / 2024 | FAIL, then supplementary PASS | CS402 FAIL `2026-MAY` REGULAR, then PASS `2026-JUL` SUPPLEMENTARY; backlogs = 0 | `get_results` lists the PASS row first |

If `MAX_BL` turns out to be above 1, S1004 and S1007 need FAILs in earlier semesters too; revisit then.

**Normal students** `S1011`–`S1030`: CSE/2023 ×4, ECE/2024 ×4, CSE/2024 ×6, ECE/2023 ×6, so every programme/batch group has 7–8 students.

## Validation results

_TODO after `scripts/validate_students.py` runs (`data/students/validation_report.txt`)._

## What the LLM got wrong

_TODO: filled in from the generator's error log._

## Known limitations

- CGPA is invented independently of the marks, so it is not derived from the results.
- Only the previous semester has results (plus one supplementary row).
