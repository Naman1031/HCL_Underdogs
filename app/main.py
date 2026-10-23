"""
FastAPI app: the fixed API contract from the brief (spec Part G). Kept thin on
purpose: each endpoint validates its input and calls one function elsewhere.
/health and /sources work now. /ask, /ingest and /audit return 501 until the
graph (step 2) and ingestion (Person A) land.
"""

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from app import db, llm
from app.schemas import AskRequest, AskResponse, HealthResponse, IngestResponse

try:
    from app import retrieval
except ImportError:  # TEMPORARY: until Person A pushes app/retrieval.py (WORKLOG section 5)
    retrieval = None

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
    # Identity comes only from the X-Student-Id header, never the question text [BRIEF R7].
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)) -> IngestResponse:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@app.get("/audit/{trace_id}")
def audit(trace_id: str) -> dict:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)
