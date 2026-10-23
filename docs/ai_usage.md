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

| `data/source_register.csv`, `data/rules.csv`, 2 synthetic documents | Claude Code (Opus 5) | Annex B register and 9 rule rows drafted from the PDFs | I checked the 75% value on page 27 of the 2022 Ordinance (clause R.1(B).22) against the PDF text myself. The two synthetic documents are team-authored and marked synthetic=Y. |
| `app/retrieval.py`, `app/ingest.py`, `scripts/load_rules.py`, `scripts/ingest_folder.py` | Claude Code (Opus 5) | Chroma + MiniLM search, pypdf chunking, loaders | `load_rules.py` run locally: 9 rules loaded. Retrieval/ingest not yet run here (model not downloaded on this laptop) - flagged in WORKLOG section 5. |

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
| 2026-10-23 | Step 2: `graph.py` (LangGraph /ask flow), `audit.py`, `/ask` and `/audit` in `main.py`, Understand and Compose prompts, `tests/test_api.py` workflow tests | Claude Code (Claude Opus 5.5) | 31 tests pass, including A's precedence tests and an end-to-end Annex A.3 case through `/ask`. Tests cover the exact `not_found` text, citations from metadata, upcoming-only documents, refusal reading no data, header-only identity, a course code invented by the LLM being dropped, what-if assumptions, no question text in the audit, and at most 2 LLM calls. Ran 3 questions against real local qwen2.5:7b-instruct: JSON valid, cited answer correct. The run found that the `other_student` category was not refused while the guardrail is a stub; fixed and tested. |
| 2026-10-23 | Final integration: tools, guardrail, live `/ingest`, number grounding check, evidence escaping, clause-aligned chunking, UI, Docker files, bootstrap, eval set and runner, README, EXPLAINED.md, data card completion | Claude Code (Claude Opus 5.5) | 66 tests pass, including edge-case tools (exactly at the threshold = ELIGIBLE, one below = NOT_ELIGIBLE), the guardrail, an invented number replaced by a template, and a document unable to close the evidence tag. All 4 demos checked live through the UI with real qwen2.5:7b-instruct. `MIN_SCORE` chosen from measured retrieval scores. The generator prompt fix was verified by a full 30-student run (0 validation errors). |
