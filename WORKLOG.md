# Team Worklog

The shared log for our 3-person team. **Every push adds one entry under your own section** at the bottom of this file. It records who built what. This file and the Git history are the input for `docs/contributions.md`, and the judges read both.

`PROJECT_SPEC.md` is the source of truth for *what* to build. This file covers *who* builds it and *how we avoid stepping on each other*.

---

## 1. Who owns what

Only the owner edits a file. If you need a change in someone else's file, ask them (chat, or under "Requests" in section 5).

| | Person A: Documents & Rules | Person B: Students, Tools & Eval | Person C: Foundation, Pipeline & Shipping |
|---|---|---|---|
| Name | Panshul | Pranjal Mann | Naman |
| `app/` | `ingest.py`, `retrieval.py`, `precedence.py` | `tools.py`, `guardrail.py` | `config.py`, `schemas.py`, `db.py`, `llm.py`, `graph.py`, `audit.py`, `main.py` |
| `scripts/` | `ingest_folder.py`, `load_rules.py` | `generate_students.py`, `validate_students.py`, `load_students.py`, `run_eval.py` | `warmup.py` |
| `data/` | `documents/`, `source_register.csv`, `rules.csv`, the 2 synthetic documents | `students/`, `prompts/` | none |
| `tests/` | `test_precedence.py` | `test_tools.py`, `test_guardrail.py` | `test_api.py`, `conftest.py` |
| Other | none | `eval/eval_set.csv`, `eval/results/`, `docs/data_card.md` | `ui/`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`, `README.md`, `docs/audit_samples/` |

**Shared files** (C creates them first, others add only in their own marked section):
- `app/schemas.py` and `app/config.py` have `# --- A ---`, `# --- B ---` and `# --- C ---` sections. Add things inside your own section only. Before changing a model someone else already uses, tell them.
- `requirements.txt`: append lines only, and mention it in your worklog entry.
- `docs/ai_usage.md`: write under your own heading only.
- `docs/contributions.md`: written together at the end.

---

## 2. Order of work

1. **C goes first (target: first hour).** Push the foundation: `requirements.txt`, `.env.example`, `config.py`, `schemas.py` (all models from the spec, with sections), `db.py` (all tables and helpers), `llm.py` (with `MOCK_LLM`), and `main.py` with `GET /health`.
2. **Meanwhile, A and B do work that needs no shared code.** A collects the DTU PDFs and fills in `source_register.csv` and `rules.csv`. B writes the edge-case plan and the generator prompts in `data/prompts/`.
3. **Everyone's first code push is stubs.** Each person pushes their module files with the **final function signatures** from section 3 and placeholder bodies, so the others can import them right away.
4. Then each person builds their part, in small pushes.

### Checkpoints (do these together)
| # | Who | Milestone |
|---|---|---|
| 1 | A + C | One real PDF ingested, one question returns a cited `retrieved_fact`, one returns `not_found` |
| 2 | B + C | Personal questions answered by tools (`calculated`), cross-student request `refused` |
| 3 | A + C | Precedence in the Policy node: superseding-circular demo and upcoming-change demo |
| 4 | All | What-if works, `run_eval.py` produces 2 reports, `docker compose up` works, rehearse the judges' flow |

---

## 3. Interfaces between parts (agree before coding; change only by telling the team)

| Provided by | Function | Used by |
|---|---|---|
| C `db.py` | `init_db()`, `query(sql, params) -> list[dict]`, `execute(sql, params)`, `get_rules(parameter) -> list[dict]`, `get_sources() -> list[dict]` | everyone |
| C `llm.py` | `chat_json(system, user, schema, mock, temperature=0) -> (model or None, usage)`, `chat_text(system, user, mock) -> (str, usage)` | C graph, B generator, A rule extraction (stretch goal) |
| A `ingest.py` | `ingest_file(path, meta: SourceMeta) -> IngestResponse` | C `POST /ingest`, A `ingest_folder.py` |
| A `retrieval.py` | `search(query: str, k: int) -> list[Chunk]`, `health() -> "ok" or "error"` | C graph, C `/health` |
| A `precedence.py` | `applicability(source, as_of_date, student) -> "current"/"upcoming"/"expired"/"out_of_scope"`, `resolve_rules(rules, sources, as_of_date, student) -> Resolution` (pure functions, no DB) | C Policy node, B tools |
| B `tools.py` | `get_student(student_id) -> StudentProfile or None`, `list_courses(student_id)`, plus the 6 tools in spec D.7, each returning `ToolResult` | C Personal and What-if nodes, B guardrail |
| B `guardrail.py` | `check(header_student_id, question, category) -> refusal message or None` | C graph |

The models (`SourceMeta`, `Rule`, `Chunk`, `Resolution`, `StudentProfile`, `ToolResult`, API models) live in `app/schemas.py`. Use the field names from the spec.

---

## 4. Git routine (everyone works on `main`)

There are no branches to manage. File ownership keeps us out of each other's way.

```
git pull --rebase origin main      # before you start, and again right before you push
# ... work, run your tests ...
git add <only your files> WORKLOG.md docs/ai_usage.md
git commit -m "<area>: <what changed>"      # e.g. "A: precedence steps 1-3 with tests"
git pull --rebase origin main
git push origin main
```

- Push small and often (at least every hour). Never use `git push --force`.
- Don't use `git add .`. Add your own files by name.
- If the rebase hits a conflict in `WORKLOG.md`, keep both sides (everyone's entries stay).
- Run `pytest` before pushing. Don't push a broken import.

---

## 5. Requests between members

_Write here when you need something from someone else's file. The owner deletes the line once it's done._

- **A → C (done):** `app/retrieval.py` is pushed with `health() -> "ok" | "error"` and a working `search()`. Imports are lazy, so importing it never breaks `/health`. Naman, you can drop the temporary import guard in `app/main.py`.
- **A → B (done):** `data/rules.csv` + `scripts/load_rules.py` are pushed. All 4 parameters you asked for are there: `min_attendance_pct` (75 from ACAD-ORD-2022 R.1(B).22 p.27, raised to **80** by the superseding circular from 2026-08-01), `pass_mark_pct` **40**, `placement_min_cgpa` **6.0**, `placement_max_backlogs` **0**. Supplementary: `supplementary_allowed_results in FAIL;ABSENT` — **DETAINED is NOT eligible** (must repeat the course), see ACAD-CIRC-2026-08 clause 3.2. Run `python scripts/load_rules.py` -> "Loaded 9 rules".
- **A → whoever has the model machine:** run `python scripts/ingest_folder.py` then `python scripts/load_rules.py`. `retrieval.py`/`ingest.py` are untested locally (no model on A's laptop).

---

## 6. Push log

Add a new entry at the **bottom of your own section** for each push:

```
### YYYY-MM-DD HH:MM: <short title>
- Files: ...
- What it does: ...
- How to check it: ...
- AI-generated? yes/no (also logged in docs/ai_usage.md)
```

### Setup

### 2026-10-23: Initial folder structure
- Files: the empty folders from PROJECT_SPEC Part E, `WORKLOG.md`, `docs/ai_usage.md`
- What it does: repo layout, ownership split, interfaces and git routine. No code yet.
- How to check it: the folders match PROJECT_SPEC Part E
- AI-generated? yes, with Claude Code (structure and this file)

### Person A: Documents & Rules

### 2026-10-23: precedence.py (Annex A) with unit tests
- Files: `app/precedence.py`, `tests/test_precedence.py`, `.gitignore`
- What it does: Annex A.2 steps 1-5 as pure functions (no DB/LLM), returning the
  shared `Resolution` from `app/schemas.py`. `applicability()` does step 1 incl.
  `2023+` / `;` scope formats; `resolve_rules()` does supersession, authority,
  recency and conflict, and writes the Annex D `precedence_decision` sentence.
- How to check it: `PYTHONPATH=. pytest tests/test_precedence.py -q` -> 10 passed.
  The brief's Annex A.3 worked example is the first test: 80%, step 2, FAQ overridden.
- Note: `.gitignore` now excludes `data/documents/*.pdf` (120MB; GitHub blocks
  >100MB). Brief section 8 allows download links, which go in source_register.csv.
- AI-generated? yes, Claude Code (reviewed by me; all 10 tests read and verified)

### 2026-10-23: source register, rules.csv, synthetic documents, ingest + retrieval
- Files: `data/source_register.csv`, `data/rules.csv`,
  `data/documents/ACAD-CIRC-2026-08.md`, `data/documents/DTU-NOTICE-2026-11.md`,
  `app/retrieval.py`, `app/ingest.py`, `scripts/load_rules.py`,
  `scripts/ingest_folder.py`, `tests/test_precedence.py`
- What it does:
  - Source Register (Annex B) for 3 real DTU documents + 2 synthetic ones.
  - 9 hand-verified rules. The real one is `min_attendance_pct >= 75` from
    ACAD-ORD-2022 clause R.1(B).22, **page 27** ("minimum attendance of 75% ...
    in order to be eligible to appear at the End-Term Examination").
  - Synthetic circular ACAD-CIRC-2026-08 supersedes that exact clause -> 80%.
    Synthetic notice DTU-NOTICE-2026-11 is future-dated (upcoming demo) and
    hides a prompt-injection line in clause 2.2 (R8 demo).
  - `retrieval.py`: MiniLM embeddings + persistent Chroma. Heavy imports are
    lazy, so the API still starts without the model and `health()` answers.
  - `ingest.py`: pypdf -> ~180-word overlapping chunks with section + page
    metadata; re-ingesting a doc_id replaces its chunks; registers the source.
- How to check it:
  - `python scripts/load_rules.py` -> "Loaded 9 rules into rule_registry."
  - `PYTHONPATH=. pytest -q` -> 21 passed.
  - Precedence on the real register: 2026-07-01 -> 75%, 2026-10-23 -> 80%
    ("ACAD-CIRC-2026-08 supersedes ACAD-ORD-2022#R.1(B).22 (step 2)"), and
    DTU-NOTICE-2026-11 reports as `upcoming`.
- Fixed: step 1 filtering used to claim to be the deciding step in
  `decision_text`; it is a filter, not a tie-break. Regression test added.
- NOT verified on this machine: `retrieval.py` and `ingest.py` need chromadb +
  sentence-transformers (~90MB model) which is not installed here. **Someone
  with the model must run `python scripts/ingest_folder.py` before the demo.**
- AI-generated? yes, Claude Code (reviewed by me; rule values read off the PDF)

### Person B: Students, Tools & Eval

### 2026-10-23: Edge-case plan and generator prompts
- Files: `data/prompts/student_system_prompt.txt`, `data/prompts/student_user_prompt.txt`, `docs/data_card.md` (draft)
- What it does: fixes which student ID carries which edge case (S1001–S1010) and how code derives the exact numbers from rule thresholds; programmes B.Tech CSE / B.Tech ECE, batches 2023 / 2024, 16 courses. Thresholds are TODO until A's `data/rules.csv` exists. No code yet.
- How to check it: read the "Edge cases" table in `docs/data_card.md`
- AI-generated? yes (also logged in docs/ai_usage.md)

### 2026-10-23: Stubs for tools and guardrail
- Files: `app/tools.py`, `app/guardrail.py`, `tests/test_tools.py`, `tests/test_guardrail.py`
- What it does: final signatures from section 3, placeholder bodies. **C: you can import these now.**
  - `tools.py`: `get_student(student_id) -> StudentProfile | None`, `list_courses(student_id) -> list[dict]` (`course_code`, `course_name`), and the 6 D.7 tools. `as_of_date` is a `"YYYY-MM-DD"` string; `check_placement_eligibility(student_id, as_of_date, assume_passed=None)`. Until step 5 every tool returns a `ToolResult` with `status="error"`.
  - `guardrail.py`: `check(header_student_id, question, category) -> str | None`, plus the fixed messages `REFUSE_OTHER_STUDENT` and `REFUSE_NOT_LOGGED_IN`. The stub allows everything for now.
- How to check it: `python -m pytest -q` (10 passed)
- AI-generated? yes (also logged in docs/ai_usage.md)

### 2026-10-23: Student data generator
- Files: `scripts/generate_students.py`, `app/schemas.py` (B section: `GeneratedStudent`, `GeneratedAttendance`, `GeneratedMarks`)
- What it does: builds `students.csv`, `courses.csv`, `attendance.csv`, `results.csv` and `generation_log.txt` in `data/students/`. Code fixes the edge-case plan (S1001–S1010) and every boundary number from thresholds resolved by `precedence.resolve_rules()`; the LLM (temperature 0.7) fills in names and the other values. Each reply is range-checked and retried (up to 3 attempts); every error caught is logged. Total, result and active_backlogs are always computed by code. Real data not generated yet: waiting for A's `rules.csv` (request in section 5).
- How to check it: after `load_rules.py`, run `python scripts/generate_students.py` (add `MOCK_LLM=true` to run without Ollama). With an empty registry it stops with `NO_RULE`. `pytest` 20 passed.
- AI-generated? yes (also logged in docs/ai_usage.md)

### 2026-10-23: Student validator and loader
- Files: `scripts/validate_students.py`, `scripts/load_students.py`
- What it does:
  - `validate_students.py`: every check in spec F.6 (columns and types, ID formats, duplicates, attended <= held, marks, total = internal + external, result vs the pass mark from `rule_registry`, programmes matching, references). On our data it also checks reserved IDs, minimum counts and all 10 planned edge cases. Writes `validation_report.txt` into the folder; exit code 1 on errors.
  - `load_students.py --dir <folder>`: runs the generic checks first and loads nothing if one fails, then upserts every CSV present in one transaction (missing files skipped). It accepts S9xxx IDs and JDG courses, and lets a folder reference students or courses already in SQLite. Loading the same folder twice is safe.
- How to check it: `python scripts/validate_students.py` then `python scripts/load_students.py --dir data/students` (judges: `docker compose exec api python scripts/load_students.py --dir /data/test_students`). `pytest` 20 passed.
- AI-generated? yes (also logged in docs/ai_usage.md)

### Person C: Foundation, Pipeline & Shipping

### 2026-10-23: Foundation (step 1, spec Phase 0)
- Files: `requirements.txt`, `.env.example`, `pytest.ini`, `app/__init__.py`, `app/config.py`, `app/schemas.py`, `app/db.py`, `app/llm.py`, `app/main.py`, `tests/conftest.py`, `tests/test_api.py`. Also, with Naman's OK: `.gitignore` (+ `data/uploads/`) and a one-line note in PROJECT_SPEC I.3
- What it does:
  - `config.py` and `schemas.py` have `# --- A ---`, `# --- B ---` and `# --- C ---` sections. **A and B: your models are already there** (A: `SourceMeta`, `Rule`, `Chunk`, `Applicability`, `Resolution`; B: `StudentProfile`, `ToolResult`, `StudentRow`, `CourseRow`, `AttendanceRow`, `ResultRow`). Check them and extend them inside your own section.
  - `db.py` creates every table from spec F.2 plus `sources` and `audit_log`. Helpers: `init_db`, `query`, `execute`, `execute_many`, `get_rules(parameter)`, `get_sources()`, `health`.
  - `llm.py`: `chat_json(system, user, schema, mock, temperature=0)` validates the reply and retries once, returning `(None, usage)` if both tries fail. `chat_text(system, user, mock, temperature=0)`. With `MOCK_LLM=true` it returns `mock` and never calls Ollama.
  - `main.py`: `GET /health` and `GET /sources` work. `/ask`, `/ingest` and `/audit` return 501 for now.
  - **Team decision (agreed with Naman):** `.env.example` uses local values (`./data/...`, `localhost:11434`). `docker-compose.yml` will set the container values itself. This replaces the values listed in PROJECT_SPEC I.3.
- How to check it:
  ```
  py -3.11 -m venv .venv
  .venv\Scripts\pip install fastapi "uvicorn[standard]" pydantic httpx pytest python-dotenv python-multipart
  .venv\Scripts\python -m pytest -q                        # 7 passed
  set MOCK_LLM=true && .venv\Scripts\python -m uvicorn app.main:app
  curl localhost:8000/health
  ```
  (Install the full `requirements.txt` when you need torch, Docling or Chroma. It is large.)
- AI-generated? yes (Claude Code), logged in docs/ai_usage.md
