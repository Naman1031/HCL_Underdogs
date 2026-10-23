"""
Embeddings and vector search over the ingested documents.

Serves R1 (answers come from retrieved text). Turns text into MiniLM vectors
and stores/searches them in a persistent ChromaDB collection, so a restart
never re-ingests anything (spec F.4).

The heavy imports (chromadb, sentence-transformers) happen inside the
functions, not at module import. That way the API still starts and /health can
honestly report "error" on a machine where the model has not been downloaded.
"""

from functools import lru_cache
from typing import Any

from app import config
from app.schemas import Chunk, SourceMeta

# Cosine distance in Chroma runs 0..2; score = 1 - distance, so 1.0 is identical.
_SPACE = "cosine"


@lru_cache(maxsize=1)
def _model():
    """Load MiniLM once per process. First call downloads ~90MB."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(config.EMBED_MODEL)


@lru_cache(maxsize=1)
def _collection():
    """Open (or create) the persistent collection on disk."""
    import chromadb

    config.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
    # We pass our own embeddings, so Chroma never picks a model for us.
    return client.get_or_create_collection(
        name=config.CHROMA_COLLECTION, metadata={"hnsw:space": _SPACE}
    )


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with MiniLM (384 dimensions)."""
    vectors = _model().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def add_chunks(
    doc_id: str, texts: list[str], metadatas: list[dict[str, Any]]
) -> int:
    """
    Replace every chunk of `doc_id` with the given ones.

    Deleting first makes re-ingesting the same doc_id idempotent, which is what
    judges do when they upload a corrected document (spec F.4).
    """
    collection = _collection()
    collection.delete(where={"doc_id": doc_id})
    if not texts:
        return 0
    ids = [f"{doc_id}::{i}" for i in range(len(texts))]
    collection.add(
        ids=ids, documents=texts, metadatas=metadatas, embeddings=embed(texts)
    )
    return len(texts)


def delete_doc(doc_id: str) -> None:
    """Remove all chunks of one document."""
    _collection().delete(where={"doc_id": doc_id})


def search(query: str, k: int | None = None) -> list[Chunk]:
    """
    Return the k closest chunks to `query`, best first.

    Filtering by applicability and precedence happens later, in the Policy node:
    this function only finds candidates, it never decides what is in force.
    """
    k = k or config.FETCH_K
    collection = _collection()
    if collection.count() == 0:
        return []

    result = collection.query(
        query_embeddings=embed([query]),
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[Chunk] = []
    for chunk_id, text, meta, distance in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                text=text,
                section=str(meta.get("section", "")),
                page=_as_int(meta.get("page")),
                score=round(1.0 - float(distance), 4),
                source=_source_from_meta(meta),
            )
        )
    return chunks


def health() -> str:
    """'ok' when the collection can be reached, else 'error' (GET /health)."""
    try:
        _collection().count()
        return "ok"
    except Exception:
        return "error"


def count() -> int:
    """Number of chunks currently indexed; used by scripts and /health."""
    try:
        return _collection().count()
    except Exception:
        return 0


# --------------------------------------------------------------------------
# Chroma stores metadata as flat strings/numbers, so we rebuild SourceMeta here
# --------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_from_meta(meta: dict[str, Any]) -> SourceMeta:
    """Rebuild the Source Register row that a chunk carries, for citations."""
    return SourceMeta(
        doc_id=str(meta.get("doc_id", "")),
        title=str(meta.get("title", "")),
        issuer=str(meta.get("issuer", "")),
        authority_level=_as_int(meta.get("authority_level")) or 5,
        doc_type=str(meta.get("doc_type", "unofficial")),
        version=str(meta.get("version", "")),
        effective_from=str(meta.get("effective_from", "")),
        effective_to=str(meta.get("effective_to", "")),
        supersedes=str(meta.get("supersedes", "")),
        scope_programmes=str(meta.get("scope_programmes", "ALL")),
        scope_batches=str(meta.get("scope_batches", "ALL")),
        synthetic=str(meta.get("synthetic", "N")),
    )
