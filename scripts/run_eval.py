"""
Runs eval/eval_set.csv through POST /ask and reports the 6 metrics of spec
Phase 8 [BRIEF Section 7, R12]. It calls the real FastAPI app in-process
(fastapi.testclient), so the full pipeline runs: retrieval, precedence, tools,
the LLM and the audit. --top-k overrides config.TOP_K, which is how the two
configurations are compared. Writes eval/results/<label>.md and <label>.csv.
Usage: python scripts/run_eval.py --label topk4 [--top-k 4]
"""

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # lets `python scripts/...` import app

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402

EVAL_SET = config.ROOT / "eval" / "eval_set.csv"
RESULTS_DIR = config.ROOT / "eval" / "results"
TOOL_VERDICTS = {"ELIGIBLE", "NOT_ELIGIBLE", "RULE_UNCERTAIN"}  # expected_answer values checked against tool output


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


def score_row(row: dict, body: dict, audit: dict) -> dict:
    """Per-question checks. None means the metric does not apply to this row."""
    expected = row["expected_answer"].strip()
    verdicts = [t["output"].get("result") for t in body["tools_invoked"]]
    cited = {(c["doc_id"], c["section"]) for c in body["citations"]}
    retrieved = {s["doc_id"] for s in audit.get("sources_retrieved", [])}
    has_doc = bool(row["expected_doc_id"])

    if expected in TOOL_VERDICTS:
        correct = expected in verdicts  # exact match on the deterministic tool's verdict
    elif expected:
        correct = expected.lower() in body["answer"].lower()  # exact substring: numbers, dates, fixed texts
    else:
        correct = None
    return {
        "type_ok": body["answer_type"] == row["expected_answer_type"],
        "answer_ok": correct,
        "citation_ok": ((row["expected_doc_id"], row["expected_section"]) in cited) if has_doc else None,
        "abstention_ok": (body["answer_type"] == "not_found") == (row["expected_answer_type"] == "not_found"),
        "tool_ok": (expected in verdicts) if expected in TOOL_VERDICTS else None,
        "retrieval_hit": (row["expected_doc_id"] in retrieved) if has_doc and row["category"] in
                         ("policy_fact", "procedure", "version_conflict") else None,
    }


def rate(scores: list[dict], key: str) -> str:
    applicable = [s[key] for s in scores if s[key] is not None]
    if not applicable:
        return "n/a"
    return f"{sum(applicable)}/{len(applicable)} ({100 * sum(applicable) / len(applicable):.0f}%)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="name of this configuration, e.g. topk4")
    parser.add_argument("--top-k", type=int, default=None, help="override TOP_K for this run")
    args = parser.parse_args()
    if args.top_k:
        config.TOP_K = args.top_k

    from app.main import app  # imported after the override, so the graph reads the new TOP_K
    client = TestClient(app)
    rows = list(csv.DictReader(EVAL_SET.open(encoding="utf-8")))

    results, scores, latencies, calls, tokens = [], [], [], [], []
    for row in rows:
        headers = {"X-Student-Id": row["student_id"]} if row["student_id"] else {}
        started = time.perf_counter()
        response = client.post("/ask", headers=headers,
                               json={"question": row["question"], "as_of_date": row["as_of_date"] or None})
        latency_ms = (time.perf_counter() - started) * 1000
        body = response.json()
        audit = client.get(f"/audit/{body['trace_id']}").json() if response.status_code == 200 else {}
        if response.status_code != 200:
            body = {"answer": f"HTTP {response.status_code}", "answer_type": "error", "citations": [],
                    "tools_invoked": [], "trace_id": ""}
        score = score_row(row, body, audit)
        scores.append(score)
        latencies.append(latency_ms)
        calls.append(audit.get("llm_calls", 0))
        tokens.append(audit.get("tokens", 0))
        results.append({"id": row["id"], "category": row["category"], "expected_type": row["expected_answer_type"],
                        "got_type": body["answer_type"], **score, "latency_ms": round(latency_ms),
                        "trace_id": body["trace_id"], "answer": body["answer"]})
        mark = "ok " if score["type_ok"] and score["answer_ok"] is not False else "BAD"
        print(f"[{mark}] {row['id']} {body['answer_type']:<20} {latency_ms / 1000:5.1f}s  {body['answer'][:80]}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / f"{args.label}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    report = [
        f"# Evaluation: {args.label}", "",
        f"- Questions: {len(rows)}; TOP_K = {config.TOP_K}; MIN_SCORE = {config.MIN_SCORE}; "
        f"FETCH_K = {config.FETCH_K}; model = {'mock' if config.MOCK_LLM else config.LLM_MODEL}",
        "- Method: exact match. A numeric or fixed-text expected answer must appear in `answer`; "
        "an eligibility verdict must equal the tool's `result`. Citation = expected (doc_id, section) "
        "is cited. Retrieval hit = expected doc_id is in the audit's `sources_retrieved` (top-k).", "",
        "| Metric | Result |", "|---|---|",
        f"| Answer type correct | {rate(scores, 'type_ok')} |",
        f"| Answer correctness | {rate(scores, 'answer_ok')} |",
        f"| Citation accuracy | {rate(scores, 'citation_ok')} |",
        f"| Abstention accuracy | {rate(scores, 'abstention_ok')} |",
        f"| Tool-result correctness | {rate(scores, 'tool_ok')} |",
        f"| Retrieval hit rate | {rate(scores, 'retrieval_hit')} |",
        f"| Latency p50 / p95 | {percentile(latencies, 50) / 1000:.1f}s / {percentile(latencies, 95) / 1000:.1f}s |",
        f"| LLM calls per question (mean) | {statistics.mean(calls):.2f} |",
        f"| Tokens per question (mean) | {statistics.mean(tokens):.0f} |", "",
        f"Per-question results: [{args.label}.csv]({args.label}.csv)",
    ]
    (RESULTS_DIR / f"{args.label}.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n" + "\n".join(report))


if __name__ == "__main__":
    main()
