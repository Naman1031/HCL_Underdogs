# University Student Services Assistant

HCLTech Future Ready AI Engineer Hackathon, team **HCL_Underdogs** (Panshul, Pranjal Mann, Naman).

An assistant that answers Delhi Technological University (DTU) student questions **only** from authorised university documents and the logged-in student's own records. Every factual answer is cited, and every eligibility decision is made by deterministic code.

> **Design in one line: the LLM explains, code decides.**
> The LLM is called at most twice per question: once to classify it, once to word the explanation. Routing, precedence between documents, eligibility, `answer_type` and citations are all plain Python that can be unit-tested.

---

## Architecture

```
 Browser ──► Streamlit UI :8501 ──HTTP JSON──┐
 Judges (curl) ─────────────────────────────►│ FastAPI :8000  (app/main.py)
                                             ▼
   POST /ask ─► Understand (LLM #1) ─► Guardrail ─► route (code)
                                          │refused       ├─► Policy:   Chroma search ─► Annex A precedence ─► MIN_SCORE check
                                          │              ├─► Personal: deterministic SQL tools + rule_registry
                                          │              ├─► What-if:  tools with assume_passed
                                          │              └─► Clarify
                                          ▼                         ▼
                                       Assemble ◄── Compose (LLM #2, number-grounding check)
                                          ▼
                                       Audit (SQLite audit_log) ─► response with trace_id

 Stores:  ChromaDB (chunks + document metadata, persisted)   SQLite (Annex C tables, sources, rule_registry, audit_log)
 Host:    Ollama qwen2.5:7b-instruct  (reached via host.docker.internal from Docker)
```

| Module | Job | Requirement |
|---|---|---|
| `app/graph.py` | LangGraph workflow: one fixed path, no agents | R1–R3, R6, R9 |
| `app/precedence.py` | Annex A source precedence as pure functions | R4 |
| `app/tools.py` | Deterministic tools: attendance, results, exam, supplementary and placement eligibility | R5 |
| `app/guardrail.py` | Identity only from `X-Student-Id`; cross-student requests refused | R7 |
| `app/retrieval.py`, `app/ingest.py` | MiniLM embeddings, persistent Chroma, PDF/Markdown chunking with section and page | R1, R11 |
| `app/audit.py` | Annex D record per answer, no question text stored | R10 |
| `app/llm.py` | Ollama JSON calls with schema, validate, retry once; `MOCK_LLM` | — |

**Why no multi-agent setup?** Routing, precedence, eligibility and authorisation are rules, not reasoning. Writing them as code makes them exact, testable and explainable. A second agent would add LLM calls, latency and failure modes without meeting any extra requirement.

---

## Run it

### Prerequisites (host)
1. [Ollama](https://ollama.com) running, with the model pulled and tested:
   ```
   ollama pull qwen2.5:7b-instruct
   ```
2. The DTU PDFs in `data/documents/`. They are git-ignored because they are 120 MB (GitHub's limit is 100 MB). Download links are in the `provenance` column of `data/source_register.csv`. The two synthetic documents (`*.md`) are in the repo.

### Option A: Docker (what the judges use)
```
docker compose up --build
```
- API: http://localhost:8000 (OpenAPI docs at `/docs`). UI: http://localhost:8501.
- On start the API runs `scripts/bootstrap.py`. It ingests `data/documents` (documents already indexed are skipped, so restarts never re-ingest), loads `data/rules.csv`, and loads `data/students/`. Chroma and SQLite live on named volumes, so they survive restarts.
- Ollama on the host is reached at `host.docker.internal:11434`. Run without a model: `MOCK_LLM=true docker compose up`.

### Option B: Local Python 3.11 (Windows)
```
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python scripts\bootstrap.py
.venv\Scripts\python -m uvicorn app.main:app --port 8000
.venv\Scripts\python -m streamlit run ui\streamlit_app.py      (second terminal)
```

### Tests
```
.venv\Scripts\python -m pytest -q
```
The tests run with `MOCK_LLM=true` and throwaway databases. They cover:
- the Annex A precedence steps, including the brief's worked example
- every tool on the edge-case students
- the guardrail
- the full `/ask` flow
- number grounding and evidence delimiting
- `/ingest` and the audit records

---

## Judges' flow

```
# 1. Ingest an unseen document while the system runs (usable on the very next /ask)
curl -X POST localhost:8000/ingest \
  -F "file=@new_circular.pdf" \
  -F 'metadata={"doc_id":"JDG-CIRC-1","title":"New circular","issuer":"Dean (Academics)","authority_level":2,"doc_type":"circular","version":"1","effective_from":"2026-10-01","supersedes":"ACAD-CIRC-2026-08#2.1","scope_programmes":"ALL","scope_batches":"ALL","synthetic":"N"}'

# 2. Load test students (Annex C CSVs) from any folder
docker compose exec api python scripts/load_students.py --dir /data/test_students     # put the CSVs in ./test_students
python scripts/load_students.py --dir test_students                                  # local run

# 3. Ask
curl -X POST localhost:8000/ask -H "Content-Type: application/json" -H "X-Student-Id: S9001" \
  -d '{"question": "Am I eligible to appear in the end-term exam for JDG101?", "as_of_date": "2026-10-23"}'
```

Note: a new circular changes **policy answers** immediately (retrieval and precedence on its metadata). A changed **numeric threshold** used by the tools comes from `rule_registry`. Add a row to `data/rules.csv` and run `python scripts/load_rules.py`, with no restart needed. If an in-force level 1–2 document supersedes the clause behind a rule and there's no replacement rule, the tools return `RULE_UNCERTAIN` and the answer is `conflict_flagged`. The system never guesses.

## Sample curl for every endpoint

```
curl localhost:8000/health
curl localhost:8000/sources
curl -X POST localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question": "What is the minimum attendance required for the end-term exam?", "as_of_date": "2026-10-23"}'
curl -X POST localhost:8000/ask -H "Content-Type: application/json" -H "X-Student-Id: S1004" \
  -d '{"question": "I failed CS401. If I pass the supplementary, will I be eligible for placement?"}'
curl localhost:8000/audit/<trace_id from a previous answer>
curl -X POST localhost:8000/ingest -F "file=@data/documents/ACAD-CIRC-2026-08.md" \
  -F 'metadata={"doc_id":"ACAD-CIRC-2026-08","title":"Circular - Revision of Minimum Attendance","issuer":"Office of the Dean (Academics)","authority_level":2,"doc_type":"circular","version":"1.0","effective_from":"2026-08-01","supersedes":"ACAD-ORD-2022#R.1(B).22","synthetic":"Y"}'
```
(On Windows `cmd`, swap the outer single quotes for double quotes and escape the inner ones, or use the UI or `/docs`.)

---

## Data

- **Documents** (`data/source_register.csv`, Annex B):
  - 3 official DTU documents: the 2022 Ordinance (level 1), the 2025 first-year Ordinance (level 1, batches 2025+), and the CSE scheme (level 3).
  - 2 synthetic documents (`synthetic = Y`). `ACAD-CIRC-2026-08` is a level-2 circular that supersedes Ordinance clause R.1(B).22, raising attendance from 75% to 80%; it also sets the pass mark, supplementary and placement rules. `DTU-NOTICE-2026-11` is a future-dated CSE notice (85%, from 2026-11-15) containing a hidden prompt-injection line.
- **Rule registry** (`data/rules.csv`): 9 rules, each linked to a document clause. The 75% value was checked by hand against page 27 of the 2022 Ordinance.
- **Students** (`data/students/`): 30 synthetic students, 2 programmes, 2 batches, 16 courses, and 10 edge-case students. Generated with `qwen2.5:7b-instruct`: code fixes every boundary value, the LLM fills in the rest. See [docs/data_card.md](docs/data_card.md) and the prompts in `data/prompts/`.

## Evaluation

`eval/eval_set.csv` has 25 questions:
- 4 not answerable
- 5 on versions and conflicts
- 8 personal, answered with tools
- 3 attempts at another student's data
- 2 multi-step
- 3 more policy and procedure questions

Run it with:
```
python scripts/run_eval.py --label topk3 --top-k 3
python scripts/run_eval.py --label topk5 --top-k 5
```
**Method:** exact match.
- A number or fixed text must appear in the answer.
- An eligibility verdict must equal the tool's `result`.
- Citation accuracy means the expected (doc_id, section) is cited.
- Retrieval hit rate means the expected doc_id is in the top-k chunks, read from the audit.
- Latency, LLM calls and tokens are also read from the audit records.

Results are in `eval/results/`.

| Metric | TOP_K = 3 | TOP_K = 5 |
|---|---|---|
| Answer type correct | 20/25 (80%) | 20/25 (80%) |
| Answer correctness | 19/23 (83%) | 19/23 (83%) |
| Citation accuracy | 15/17 (88%) | 15/17 (88%) |
| Abstention accuracy | 23/25 (92%) | 23/25 (92%) |
| Tool-result correctness | 7/8 (88%) | 7/8 (88%) |
| Retrieval hit rate | 7/9 (78%) | 7/9 (78%) |
| Latency p50 / p95 | 23.9 s / 40.2 s | 22.0 s / 31.0 s |
| LLM calls / tokens per question | 1.64 / 893 | 1.64 / 1040 |

**Chosen: TOP_K = 3.** Accuracy is identical, and it uses about 15% fewer tokens per question. (Latency differences come from the local model being shared with the running app, not from TOP_K.)

**What the evaluation found, and what we changed.** All 6 misses came from the 7B model mislabelling the question category: general questions were treated as personal, an "am I / can I" question was treated as policy, and off-topic questions were labelled other_student or unclear. We added deterministic code checks after the Understand step (no "I/me/my" means it can't be personal; "am I / can I" means it is personal eligibility; unclear questions search and abstain if evidence is weak), plus tests. These numbers were measured **before** that fix. A rerun is the next step. The other remaining miss (E05) is wording only: the right answer type and citation, but the one-line answer left out the number.


## Assumptions
- `as_of_date` defaults to today. Every precedence decision is made relative to it.
- A general question (no `X-Student-Id`) only applies documents scoped `ALL`. Programme-specific documents need a logged-in student.
- Marks scheme for synthetic data: internal 40 + external 60 = 100.
- A what-if "if I pass X" treats X's latest result as PASS and removes it from the backlog count.

## Limitations and known edge cases
- **No OCR.** Text is extracted with `pypdf`. A scanned PDF page with no text layer is skipped, and `/ingest` reports it in `detail` instead of failing silently. Docling and OCR were dropped to keep the image small and the build reliable.
- A new circular's **numeric** thresholds reach the tools only through `rule_registry` (one CSV row and `load_rules.py`). Automatic rule extraction at ingest was out of scope. The `RULE_UNCERTAIN` safety net prevents wrong verdicts in the meantime.
- What-if questions are supported for placement ("if I pass X…"). Other hypotheticals are answered from the current records, without assumptions.
- A cold local 7B model takes about 60–90 s on the first question; later questions take about 5–15 s on CPU.
- Section detection is heuristic (clause-number regex), so some chunks of the real PDFs carry the nearest previous clause number.

## LLM fallback disclosure
Only the local Ollama model was used. `LLM_BACKEND=cloud` exists as a switch, but no cloud backend is implemented or used.

## Deliverables
[Source register](data/source_register.csv) · [Rules](data/rules.csv) · [Data card](docs/data_card.md) · [Prompts](data/prompts/) · [Eval set](eval/eval_set.csv) · [Eval results](eval/results/) · [Audit samples](docs/audit_samples/) · [AI-usage disclosure](docs/ai_usage.md) · [Contributions](docs/contributions.md) · [Team worklog](WORKLOG.md)
