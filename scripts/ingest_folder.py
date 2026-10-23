"""
One-time ingest of data/documents using data/source_register.csv.

Each register row names a document; we look for a file whose name starts with
the doc_id, else fall back to the `file` column, else try to match on title.
Documents already indexed are skipped unless --force is given, so re-running
this is cheap (R11: no re-ingest on restart).

Usage:  python scripts/ingest_folder.py [--force] [--only DOC-ID]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402
from app.ingest import ingest_file  # noqa: E402
from app.schemas import SourceMeta  # noqa: E402

SUFFIXES = (".pdf", ".md", ".txt", ".html", ".docx")


def find_file(doc_id: str, title: str) -> Path | None:
    """Match a register row to a file in data/documents."""
    folder = config.DOCUMENTS_DIR
    for suffix in SUFFIXES:
        exact = folder / f"{doc_id}{suffix}"
        if exact.exists():
            return exact
    # Fall back to a loose title match, so the real DTU filenames still work.
    words = [w.lower() for w in title.split() if len(w) > 4][:3]
    for path in folder.iterdir():
        if path.suffix.lower() not in SUFFIXES:
            continue
        name = path.name.lower()
        if words and all(w in name for w in words):
            return path
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-ingest even if indexed")
    parser.add_argument("--only", default=None, help="ingest just this doc_id")
    args = parser.parse_args()

    db.init_db()
    already = {
        row["doc_id"]
        for row in db.query("SELECT doc_id FROM sources WHERE chunks_indexed > 0")
    }

    with config.SOURCE_REGISTER_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    total = 0
    for row in rows:
        doc_id = row["doc_id"].strip()
        if args.only and doc_id != args.only:
            continue
        if doc_id in already and not args.force:
            print(f"- {doc_id}: already indexed, skipping")
            continue

        path = find_file(doc_id, row.get("title", ""))
        if path is None:
            print(f"! {doc_id}: no matching file in {config.DOCUMENTS_DIR}")
            continue

        meta = SourceMeta(**{k: (v or "").strip() for k, v in row.items()
                             if k in SourceMeta.model_fields})
        result = ingest_file(path, meta)
        total += result.chunks_indexed
        mark = "+" if result.status == "indexed" else "!"
        print(f"{mark} {doc_id}: {result.chunks_indexed} chunks "
              f"from {path.name}{' - ' + result.detail if result.detail else ''}")

    print(f"\nTotal chunks indexed this run: {total}")


if __name__ == "__main__":
    main()
