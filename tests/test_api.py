"""
API contract tests (spec Part G) plus the LLM JSON retry (spec D.3 node 1).
Run with MOCK_LLM=true (set in conftest.py), so no Ollama is needed.
"""

import httpx
from fastapi.testclient import TestClient

from app import config, llm
from app.main import app
from app.schemas import Understanding

client = TestClient(app)


def test_health_reports_every_component():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"api", "vector_store", "sqlite", "llm"}
    assert body["api"] == "ok"
    assert body["sqlite"] == "ok"
    assert body["llm"] == "mock"
    assert body["vector_store"] in {"ok", "error"}


def test_sources_returns_a_list():
    response = client.get("/sources")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_unbuilt_endpoints_say_not_implemented():
    assert client.post("/ask", json={"question": "hi"}).status_code == 501
    assert client.get("/audit/abcd1234").status_code == 501


def test_ask_rejects_a_badly_formatted_date():
    response = client.post("/ask", json={"question": "hi", "as_of_date": "06-10-2026"})
    assert response.status_code == 422


def test_chat_json_retries_once_then_gives_up(monkeypatch):
    # Pretend Ollama is up but keeps returning broken JSON.
    replies = iter(['{"category": "not-a-category"}', "not json at all"])
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(llm, "_chat", lambda messages, schema, temperature: (next(replies), 10))
    mock = Understanding(category="unclear")

    result, usage = llm.chat_json("system", "user", Understanding, mock)

    assert result is None
    assert usage.calls == 2
    assert usage.tokens == 20


def test_chat_json_accepts_a_valid_reply_after_one_bad_one(monkeypatch):
    replies = iter(["oops", '{"category": "policy_fact", "search_query": "minimum attendance"}'])
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(llm, "_chat", lambda messages, schema, temperature: (next(replies), 5))
    mock = Understanding(category="unclear")

    result, usage = llm.chat_json("system", "user", Understanding, mock)

    assert result is not None and result.category == "policy_fact"
    assert usage.calls == 2


def test_llm_health_reports_error_when_ollama_is_down(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(httpx, "get", refuse)
    assert llm.health() == "error"
