# AI-usage disclosure

The brief requires this. Record every piece of AI-assisted work: what was generated, in which phase, and how it was verified. Write under your own heading only, so we avoid merge conflicts.

## Setup

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Folder structure, `WORKLOG.md`, this file | Claude Code | Folders compared against PROJECT_SPEC Part E by the team |

## Person A: Documents & Rules

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|

## Person B: Students, Tools & Eval

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Edge-case plan (`docs/data_card.md` draft) and generator prompts in `data/prompts/` | Claude Code | Checked against spec F.6 edge-case list; prompt placeholders test-filled with Python `string.Template` |

## Person C: Foundation, Pipeline & Shipping

| Date | What was generated | Tool | How it was verified |
|---|---|---|---|
| 2026-10-23 | Step 1 foundation: `config.py`, `schemas.py`, `db.py`, `llm.py`, `main.py` (`/health`, `/sources`), `requirements.txt`, `.env.example`, pytest setup, `tests/test_api.py` | Claude Code (Claude Opus 5.5) | `pytest` passes 7 tests, covering `/health`, `/sources`, date validation, and LLM JSON retry/give-up with Ollama faked. Started uvicorn and checked `/health` with `MOCK_LLM=true` (`llm: mock`) and with real Ollama (`llm: ok`). SQL tables compared line by line against spec F.2. |
