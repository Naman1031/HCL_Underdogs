"""
Load data/rules.csv into the rule_registry table.

Serves R5: every threshold a tool uses comes from this table, and every row
points at the document clause it was read from. Hand-verified rows are loaded
with origin='manual'.

Usage:  python scripts/load_rules.py [--file data/rules.csv]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402

COLUMNS = [
    "rule_id", "description", "parameter", "operator", "value",
    "scope_programmes", "scope_batches", "effective_from", "effective_to",
    "source_doc_id", "source_section", "origin",
]


def load(path: Path) -> int:
    db.init_db()
    known_docs = {row["doc_id"] for row in db.get_sources()}

    rows, skipped = [], []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            missing = [c for c in COLUMNS if c not in row]
            if missing:
                raise SystemExit(f"{path} is missing columns: {missing}")
            # A rule must point at a registered document, or its authority is
            # unknown and precedence cannot rank it (Annex C).
            if known_docs and row["source_doc_id"] not in known_docs:
                skipped.append(f"{row['rule_id']} -> unknown doc {row['source_doc_id']}")
                continue
            rows.append(tuple(row[c].strip() for c in COLUMNS))

    db.execute_many(
        f"INSERT OR REPLACE INTO rule_registry ({','.join(COLUMNS)}) "
        f"VALUES ({','.join('?' * len(COLUMNS))})",
        rows,
    )

    for line in skipped:
        print(f"  skipped: {line}")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=str(config.RULES_CSV))
    args = parser.parse_args()

    count = load(Path(args.file))
    print(f"Loaded {count} rules into rule_registry.")
    for row in db.query("SELECT parameter, COUNT(*) n FROM rule_registry GROUP BY parameter"):
        print(f"  {row['parameter']}: {row['n']}")


if __name__ == "__main__":
    main()
