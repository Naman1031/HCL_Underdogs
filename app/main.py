"""
FastAPI app: the fixed API contract from the brief (spec Part G). Kept thin on
purpose: each endpoint validates its input and calls one function elsewhere.
Identity for /ask comes only from the X-Student-Id header [BRIEF R7].
/ingest returns 501 until Person A's ingest_file() lands.
"""

from datetime import date

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from app import audit, db, llm
from app.schemas import AskRequest, AskResponse, HealthResponse, IngestResponse

# TEMPORARY guards: until Persons A and B push their modules (WORKLOG section 5),
# the API still starts and /health still answers. Remove once their files are on main.
try:
    from app import retrieval
except ImportError:
    retrieval = None
try:
    from app import graph
except ImportError:  # graph.py imports A's and B's modules
    graph = None

app = FastAPI(title="University Student Services Assistant")

# Creating tables at import keeps startup simple (no async lifespan needed).
# CREATE TABLE IF NOT EXISTS makes it a no-op once the tables exist.
db.init_db()

NOT_IMPLEMENTED = "Not implemented yet. See WORKLOG.md for progress."


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        api="ok",
        vector_store=retrieval.health() if retrieval else "error",
        sqlite=db.health(),
        llm=llm.health(),
    )


@app.get("/sources")
def sources() -> list[dict]:
    return db.get_sources()


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, x_student_id: str | None = Header(default=None)) -> AskResponse:
    if graph is None:
        raise HTTPException(status_code=503, detail="The answering pipeline is not available yet.")
    as_of_date = body.as_of_date or date.today().isoformat()
    try:
        return graph.run_ask(body.question, as_of_date, x_student_id or None)
    except httpx.HTTPError:
        # Better an honest error than an answer produced without the model's checks.
        raise HTTPException(status_code=503, detail="The language model is not reachable.")


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)) -> IngestResponse:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@app.get("/audit/{trace_id}")
def get_audit(trace_id: str) -> dict:
    record = audit.read(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No audit record with this trace_id.")
    return record
