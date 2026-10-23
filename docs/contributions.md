# Team contribution statement

Team HCL_Underdogs. Who built which part. The Git history and [WORKLOG.md](../WORKLOG.md) give the detail, commit by commit. Every member reviewed the whole system and can explain every module.

| Member | Role | Built |
|---|---|---|
| **Panshul** | A: Documents & Rules | Project specification; document selection; Source Register (Annex B); hand-verified `rules.csv`, with the 75% clause checked on page 27 of the 2022 Ordinance; the two synthetic documents (superseding circular, future-dated notice with injection line); `app/precedence.py` (Annex A steps 1–5, pure functions) and its tests; `app/retrieval.py` (MiniLM + persistent Chroma); `app/ingest.py` (text extraction, chunking, source registration); `scripts/load_rules.py`, `scripts/ingest_folder.py` |
| **Pranjal Mann** | B: Students, Tools & Eval | Edge-case plan and data card; verbatim generator prompts; `scripts/generate_students.py` (code fixes every boundary value, the LLM fills the rest, errors logged); `scripts/validate_students.py`; `scripts/load_students.py` (judges' loader); tool and guardrail interfaces |
| **Naman** | C: Foundation, Pipeline & Shipping | Repo structure and team workflow; `app/config.py`, `schemas.py`, `db.py`, `llm.py`; `app/graph.py` (LangGraph workflow, number grounding check, evidence delimiting); `app/audit.py`; `app/main.py` (API contract); Streamlit UI; Dockerfile and docker-compose; README |

**Completed on Naman's machine at the end of the build day**, with the team's agreement, after A and B handed over their parts. All of it was written with Claude Code and reviewed:
- `app/tools.py` and `app/guardrail.py` bodies, built to Pranjal's interfaces and edge-case plan
- clause-aligned chunking in `app/ingest.py` and the `file` column in the register
- `scripts/run_eval.py` and `eval/eval_set.csv`
- the data run (ingest, rules, student generation) and the evaluation runs

AI coding assistants were used throughout; see [ai_usage.md](ai_usage.md).
