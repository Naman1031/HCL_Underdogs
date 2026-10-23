"""
FastAPI app: the fixed API contract from the brief (spec Part G). Kept thin on
purpose: each endpoint validates its input and calls one function elsewhere.
Identity for /ask comes only from the X-Student-Id header [BRIEF R7].
/ingest indexes synchronously, so a new document answers the next /ask [BRIEF R11].
"""

from datetime import date
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import ValidationError

from app import audit, config, db, graph, ingest, llm, retrieval
from app.schemas import AskRequest, AskResponse, HealthResponse, IngestResponse, SourceMeta

ALLOWED_SUFFIXES = {".pdf", ".md", ".txt", ".html", ".htm"}

app = FastAPI(title="University Student Services Assistant")

# Creating tables at import keeps startup simple (no async lifespan needed).
# CREATE TABLE IF NOT EXISTS makes it a no-op once the tables exist.
db.init_db()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        api="ok",
        vector_store=retrieval.health(),
        sqlite=db.health(),
        llm=llm.health(),
    )


@app.get("/sources")
def sources() -> list[dict]:
    return db.get_sources()


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, x_student_id: str | None = Header(default=None)) -> AskResponse:
    as_of_date = body.as_of_date or date.today().isoformat()
    student_id = (x_student_id or "").strip().upper() or None
    try:
        return graph.run_ask(body.question, as_of_date, student_id)
    except httpx.HTTPError:
        # Better an honest error than an answer produced without the model's checks.
        raise HTTPException(status_code=503, detail="The language model is not reachable.")


@app.post("/ingest", response_model=IngestResponse)
def ingest_document(file: UploadFile = File(...), metadata: str = Form(...)) -> IngestResponse:
    try:
        meta = SourceMeta.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"metadata is not a valid Source Register row: {exc}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"unsupported file type {suffix!r}; "
                                                    f"use one of {sorted(ALLOWED_SUFFIXES)}")
    # Saved under the doc_id (validated as a safe file name), never the uploaded name.
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UPLOADS_DIR / f"{meta.doc_id}{suffix}"
    path.write_bytes(file.file.read())
    return ingest.ingest_file(path, meta)


@app.get("/audit/{trace_id}")
def get_audit(trace_id: str) -> dict:
    record = audit.read(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No audit record with this trace_id.")
    return record
