"""
Downloads the embedding model at Docker build time (spec I.1), so the first
/ingest or /ask in front of the judges never stalls on a ~90MB download.
Usage: python scripts/warmup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # lets `python scripts/...` import app

from app import retrieval  # noqa: E402


def main() -> None:
    vectors = retrieval.embed(["warm-up sentence"])
    print(f"Embedding model ready ({len(vectors[0])} dimensions).")


if __name__ == "__main__":
    main()
