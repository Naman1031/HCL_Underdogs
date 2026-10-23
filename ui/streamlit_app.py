"""
Minimal Streamlit UI [BRIEF Section 5: only usability is scored]. It talks to
the FastAPI service over HTTP, exactly like a judge with curl, so the UI holds
no logic of its own. Tabs: Ask (student ID, question, as_of_date), Ingest a
document, and the Source Register.
"""

import json
import os
from datetime import date

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
ASK_TIMEOUT_S = 300  # a cold local 7B model can take a minute or more on the first question
INGEST_TIMEOUT_S = 600

ANSWER_TYPE_LABELS = {
    "retrieved_fact": "Retrieved fact (quoted from a cited document)",
    "calculated": "Calculated by a deterministic tool",
    "not_found": "Not found in the authorised sources",
    "clarification_needed": "Clarification needed",
    "refused": "Refused",
    "conflict_flagged": "Conflict flagged (sources disagree)",
}

METADATA_TEMPLATE = {
    "doc_id": "NEW-CIRC-2026-01", "title": "New circular", "issuer": "Office of the Dean (Academics)",
    "authority_level": 2, "doc_type": "circular", "version": "1.0", "effective_from": date.today().isoformat(),
    "effective_to": "", "supersedes": "", "scope_programmes": "ALL", "scope_batches": "ALL",
    "provenance": "", "retrieved_on": date.today().isoformat(), "synthetic": "N",
}

st.set_page_config(page_title="Student Services Assistant", page_icon="🎓", layout="wide")
st.title("University Student Services Assistant")
st.caption("Answers only from authorised university documents and your own records. "
           "The LLM explains; code decides.")

ask_tab, ingest_tab, sources_tab = st.tabs(["Ask", "Ingest a document", "Sources"])


def show_error(response: httpx.Response) -> None:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    st.error(f"{response.status_code}: {detail}")


with ask_tab:
    left, right = st.columns([1, 3])
    with left:
        student_id = st.text_input("Student ID (log in)", placeholder="e.g. S1001",
                                   help="Leave empty for general questions. Sent as the X-Student-Id header.")
        as_of = st.date_input("As of date", value=date.today())
    with right:
        question = st.text_area("Your question", height=100,
                                placeholder="What is the minimum attendance required for the end-term exam?")
        asked = st.button("Ask", type="primary", disabled=not question.strip())

    if asked:
        headers = {"X-Student-Id": student_id.strip()} if student_id.strip() else {}
        with st.spinner("Thinking..."):
            try:
                response = httpx.post(f"{API_URL}/ask", headers=headers, timeout=ASK_TIMEOUT_S,
                                      json={"question": question, "as_of_date": as_of.isoformat()})
            except httpx.HTTPError as exc:
                st.error(f"Could not reach the API at {API_URL}: {exc}")
                st.stop()
        if response.status_code != 200:
            show_error(response)
            st.stop()

        data = response.json()
        st.markdown(f"**{ANSWER_TYPE_LABELS.get(data['answer_type'], data['answer_type'])}**")
        st.subheader(data["answer"])
        if data["explanation"]:
            st.write(data["explanation"])
        for note in data.get("assumptions", []):
            st.info(f"Assumption: {note}")
        for note in data.get("upcoming_changes", []):
            st.warning(f"Upcoming change: {note}")
        for note in data["conflicts_detected"]:
            st.caption(f"Precedence: {note}")

        if data["citations"]:
            st.markdown("**Sources**")
            st.dataframe(data["citations"], hide_index=True, use_container_width=True)
        if data["applied_rules"]:
            st.markdown("**Rules applied**")
            st.dataframe(data["applied_rules"], hide_index=True, use_container_width=True)
        if data["tools_invoked"]:
            with st.expander("Tools invoked (inputs and outputs)"):
                st.json(data["tools_invoked"])

        with st.expander(f"Audit record (trace_id {data['trace_id']})"):
            audit = httpx.get(f"{API_URL}/audit/{data['trace_id']}", timeout=10)
            st.json(audit.json() if audit.status_code == 200 else {"error": audit.text})

with ingest_tab:
    st.write("Upload a document and its Source Register metadata (Annex B). "
             "It is searchable on the very next question, with no restart.")
    upload = st.file_uploader("Document", type=["pdf", "md", "txt", "html"])
    metadata = st.text_area("Metadata (JSON)", value=json.dumps(METADATA_TEMPLATE, indent=2), height=360)
    if st.button("Ingest", type="primary", disabled=upload is None):
        with st.spinner("Parsing, chunking and indexing..."):
            try:
                response = httpx.post(f"{API_URL}/ingest", timeout=INGEST_TIMEOUT_S,
                                      files={"file": (upload.name, upload.getvalue())},
                                      data={"metadata": metadata})
            except httpx.HTTPError as exc:
                st.error(f"Could not reach the API at {API_URL}: {exc}")
                st.stop()
        if response.status_code != 200:
            show_error(response)
        else:
            result = response.json()
            (st.success if result["status"] == "indexed" else st.error)(
                f"{result['doc_id']}: {result['status']}, {result['chunks_indexed']} chunks"
                + (f" ({result['detail']})" if result.get("detail") else ""))

with sources_tab:
    try:
        health = httpx.get(f"{API_URL}/health", timeout=10).json()
        st.write("System health: " + ", ".join(f"{k} **{v}**" for k, v in health.items()))
        rows = httpx.get(f"{API_URL}/sources", timeout=10).json()
        st.dataframe(rows, hide_index=True, use_container_width=True)
    except httpx.HTTPError as exc:
        st.error(f"Could not reach the API at {API_URL}: {exc}")
