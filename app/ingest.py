"""
Document ingestion: parse, chunk, embed and register a document.

Serves R11 (live ingestion). A document uploaded through POST /ingest is
searchable on the very next /ask, with no restart: we index synchronously and
Chroma is persisted to disk.

Text extraction uses pypdf for PDFs and a plain read for .md/.txt/.html.
Scanned pages yield no text; we report that in `detail` rather than failing
silently, so a judge can see which pages need OCR.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from app import config, db, retrieval
from app.schemas import IngestResponse, SourceMeta

# A chunk is cut at roughly this many words. MiniLM truncates above 256 word
# pieces, and words are fewer than word-pieces, so this stays safely inside it.
WORDS_PER_CHUNK = 180
CHUNK_OVERLAP_WORDS = 30  # only used when one clause is longer than a chunk
MIN_CHUNK_WORDS = 5  # drops stray page numbers and headers, keeps short clauses
SHORT_UNIT_WORDS = 12  # shorter units (table rows, headings) join the previous chunk

# "R.1(B).22", "7.2", "Annexure - 3". Clause parts have 1-2 digits and are followed by a
# space, so table values such as "163.87" or "43.110" are not mistaken for clause numbers.
SECTION_PATTERN = re.compile(
    r"^\s*(?:#+\s*)?((?:R\.\s?\d+\([A-Z]\)\.\d+)|(?:\d{1,2}(?:\.\d{1,2})+(?=\s))|(?:Annexure\s*-?\s*\d+))",
    re.MULTILINE,
)


def extract_pages(path: Path) -> list[str]:
    """Return one string per page. Non-PDF files come back as a single page."""
    if path.suffix.lower() != ".pdf":
        return [path.read_text(encoding="utf-8", errors="ignore")]

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def find_section(text: str, fallback: str) -> str:
    """Nearest clause or heading number in this chunk, for the citation."""
    match = SECTION_PATTERN.search(text)
    return match.group(1).strip() if match else fallback


def clause_units(pages: list[str]) -> list[tuple[list[str], int, str]]:
    """
    Split pages into clause units: (words, page_number, section).

    A new unit starts at every line that begins with a clause number, so a chunk
    can cite the clause it actually contains (R2). Lines before the first clause
    keep the previous section (or "" at the start of a document).
    """
    units: list[tuple[list[str], int, str]] = []
    section = ""
    for page_no, raw in enumerate(pages, start=1):
        current: list[str] | None = None  # never continue a unit across pages: the page must stay exact
        for line in raw.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if not line:
                continue
            match = SECTION_PATTERN.match(line)
            if match:
                section, current = match.group(1).strip(), None
            if current is None:
                current = []
                units.append((current, page_no, section))
            current.extend(line.split())
    return units


def chunk_pages(pages: list[str]) -> list[tuple[str, int, str]]:
    """
    One chunk per clause, so each chunk's section is the clause it holds.

    Returns (text, page_number, section). A chunk never spans two pages. Very
    short units (table rows, headings) join the previous chunk instead of standing
    alone; a clause longer than WORDS_PER_CHUNK is cut into overlapping windows.
    Scanned pages (no text layer) yield nothing.
    """
    chunks: list[tuple[str, int, str]] = []
    words: list[str] = []
    page, section = 0, ""
    for unit_words, unit_page, unit_section in clause_units(pages):
        joins_previous = (len(unit_words) < SHORT_UNIT_WORDS and unit_page == page
                          and len(words) + len(unit_words) <= WORDS_PER_CHUNK)
        if words and not joins_previous:
            chunks.append((" ".join(words), page, section))
            words = []
        if not words:
            page, section = unit_page, unit_section
        words += unit_words
        while len(words) > WORDS_PER_CHUNK:
            chunks.append((" ".join(words[:WORDS_PER_CHUNK]), page, section))
            words = words[WORDS_PER_CHUNK - CHUNK_OVERLAP_WORDS:]
    if words:
        chunks.append((" ".join(words), page, section))
    # Some PDFs repeat whole pages; identical chunks would only crowd out other evidence in top-k.
    seen: set[str] = set()
    unique = []
    for chunk in chunks:
        if len(chunk[0].split()) >= MIN_CHUNK_WORDS and chunk[0] not in seen:
            seen.add(chunk[0])
            unique.append(chunk)
    return unique


def register_source(meta: SourceMeta, chunks_indexed: int) -> None:
    """Upsert the Annex B row into SQLite so GET /sources can return it."""
    db.execute(
        """
        INSERT INTO sources (doc_id, title, issuer, authority_level, doc_type,
                             version, effective_from, effective_to, supersedes,
                             scope_programmes, scope_batches, provenance,
                             retrieved_on, synthetic, chunks_indexed, ingested_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(doc_id) DO UPDATE SET
            title=excluded.title, issuer=excluded.issuer,
            authority_level=excluded.authority_level, doc_type=excluded.doc_type,
            version=excluded.version, effective_from=excluded.effective_from,
            effective_to=excluded.effective_to, supersedes=excluded.supersedes,
            scope_programmes=excluded.scope_programmes,
            scope_batches=excluded.scope_batches, provenance=excluded.provenance,
            retrieved_on=excluded.retrieved_on, synthetic=excluded.synthetic,
            chunks_indexed=excluded.chunks_indexed, ingested_at=excluded.ingested_at
        """,
        (
            meta.doc_id, meta.title, meta.issuer, meta.authority_level,
            meta.doc_type, meta.version, meta.effective_from, meta.effective_to,
            meta.supersedes, meta.scope_programmes, meta.scope_batches,
            meta.provenance, meta.retrieved_on, meta.synthetic, chunks_indexed,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )


def ingest_file(path: str | Path, meta: SourceMeta) -> IngestResponse:
    """
    Parse, chunk, embed and register one document.

    Re-ingesting the same doc_id replaces its chunks, so judges can upload a
    corrected version and ask about it immediately.
    """
    path = Path(path)
    if not path.exists():
        return IngestResponse(doc_id=meta.doc_id, chunks_indexed=0,
                              status="error", detail=f"file not found: {path}")

    try:
        pages = extract_pages(path)
    except Exception as exc:
        return IngestResponse(doc_id=meta.doc_id, chunks_indexed=0,
                              status="error", detail=f"could not read {path.name}: {exc}")

    pieces = chunk_pages(pages)
    if not pieces:
        # Every page was an image: the document needs OCR, which we do not run.
        register_source(meta, 0)
        return IngestResponse(
            doc_id=meta.doc_id, chunks_indexed=0, status="error",
            detail=f"no extractable text in {len(pages)} pages; "
                   "the document appears to be scanned and needs OCR",
        )

    # Every chunk carries its document's Annex B metadata, so a citation can be
    # built from the chunk alone without a second database lookup.
    base = meta.model_dump()
    metadatas = [
        {**base, "section": section, "page": page, "chunk_no": i}
        for i, (_, page, section) in enumerate(pieces)
    ]

    try:
        indexed = retrieval.add_chunks(meta.doc_id, [t for t, _, _ in pieces], metadatas)
    except Exception as exc:
        return IngestResponse(doc_id=meta.doc_id, chunks_indexed=0,
                              status="error", detail=f"indexing failed: {exc}")

    register_source(meta, indexed)
    return IngestResponse(doc_id=meta.doc_id, chunks_indexed=indexed, status="indexed")
