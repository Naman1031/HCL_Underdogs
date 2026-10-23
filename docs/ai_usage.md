# AI-usage disclosure

The brief requires this. Record every piece of AI-assisted work: what was generated, in which phase, and how it was verified. Write under your own heading only, so we avoid merge conflicts.

## Setup

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Folder structure, `WORKLOG.md`, this file | Claude Code | Folders compared against PROJECT_SPEC Part E by the team |

## Person A: Documents & Rules

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|

| `app/precedence.py`, `tests/test_precedence.py` | Claude Code (Opus 5) | Annex A steps 1-5 + 10 unit tests | I read every function and every test; the Annex A.3 worked example from the brief passes exactly (80%, step 2). Ran `pytest` locally: 10 passed. |

## Person B: Students, Tools & Eval

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Edge-case plan (`docs/data_card.md` draft) and generator prompts in `data/prompts/` | Claude Code | Checked against spec F.6 edge-case list; prompt placeholders test-filled with Python `string.Template` |
| 2026-10-23 | Stubs: `app/tools.py`, `app/guardrail.py` and their stub tests | Claude Code | Signatures compared with WORKLOG section 3 and spec D.7; `pytest` 10 passed |
| 2026-10-23 | `scripts/generate_students.py` and the generator models in `app/schemas.py` | Claude Code | Mock dry run: all 10 edge cases checked by hand (e.g. 30/40 and 29/40 at 75%, CGPA 7.00/6.99). A fake LLM returning bad replies confirmed errors are logged and retried, and fixed values are kept. End-to-end run against a test rule registry; empty registry stops with `NO_RULE`. `pytest` 20 passed |
| 2026-10-23 | `scripts/validate_students.py`, `scripts/load_students.py` | Claude Code | Against a test rule registry: mock-generated data passes (0 errors); a copy with 6 deliberate breaks (attended > held, wrong total, wrong result, missing ABSENT edge case, S9xxx ID, JDG course, bad ID) fails with each one reported. Loader: loading twice keeps the same row counts, a broken folder loads nothing, a judges-style folder (S9001, JDG101, no attendance.csv) loads. `pytest` 20 passed |

## Person C: Foundation, Pipeline & Shipping

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Step 1 foundation: `config.py`, `schemas.py`, `db.py`, `llm.py`, `main.py` (`/health`, `/sources`), `requirements.txt`, `.env.example`, pytest setup, `tests/test_api.py` | Claude Code (Claude Opus 5.5) | `pytest` passes 7 tests, covering `/health`, `/sources`, date validation, and LLM JSON retry/give-up with Ollama faked. Started uvicorn and checked `/health` with `MOCK_LLM=true` (`llm: mock`) and with real Ollama (`llm: ok`). SQL tables compared line by line against spec F.2. |
