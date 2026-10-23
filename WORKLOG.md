# Team Worklog

The shared log for our 3-person team. **Every push adds one entry under your own section** at the bottom of this file. It records who built what. This file and the Git history are the input for `docs/contributions.md`, and the judges read both.

`PROJECT_SPEC.md` is the source of truth for *what* to build. This file covers *who* builds it and *how we avoid stepping on each other*.

---

## 1. Who owns what

Only the owner edits a file. If you need a change in someone else's file, ask them (chat, or under "Requests" in section 5).

| | Person A: Documents & Rules | Person B: Students, Tools & Eval | Person C: Foundation, Pipeline & Shipping |
|---|---|---|---|
| Name | Panshul | Pranjal | Naman |
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

- **C → A (Naman → Panshul):** please push `app/retrieval.py` with `health() -> "ok" | "error"` (Chroma `heartbeat()`) early, even if `search()` is still a stub. `/health` reports `vector_store: "error"` until then. Once it lands, C removes the temporary import guard in `app/main.py`.

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

### Person B: Students, Tools & Eval

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
