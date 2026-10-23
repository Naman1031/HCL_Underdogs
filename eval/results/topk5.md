# Evaluation: topk5

- Questions: 25; TOP_K = 5; MIN_SCORE = 0.5; FETCH_K = 20; model = qwen2.5:7b-instruct
- Method: exact match. A numeric or fixed-text expected answer must appear in `answer`; an eligibility verdict must equal the tool's `result`. Citation = expected (doc_id, section) is cited. Retrieval hit = expected doc_id is in the audit's `sources_retrieved` (top-k).

| Metric | Result |
|---|---|
| Answer type correct | 20/25 (80%) |
| Answer correctness | 19/23 (83%) |
| Citation accuracy | 15/17 (88%) |
| Abstention accuracy | 23/25 (92%) |
| Tool-result correctness | 7/8 (88%) |
| Retrieval hit rate | 7/9 (78%) |
| Latency p50 / p95 | 22.0s / 31.0s |
| LLM calls per question (mean) | 1.64 |
| Tokens per question (mean) | 1040 |

Per-question results: [topk5.csv](topk5.csv)
