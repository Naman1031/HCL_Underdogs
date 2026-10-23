"""
Prepares the stores so `docker compose up` (or a fresh laptop) is ready to answer:
ingests data/documents (skipping documents already indexed, so restarts never
re-ingest [spec A.3]), loads data/rules.csv, and loads data/students if present.
Every step is idempotent, so running it on every start is safe.
Usage: python scripts/bootstrap.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS = [  # (description, command); order matters: rules need sources, students need rules
    ("Ingest documents", ["scripts/ingest_folder.py"]),
    ("Load rules", ["scripts/load_rules.py"]),
    ("Load students", ["scripts/load_students.py", "--dir", "data/students"]),
]


def main() -> None:
    for description, args in STEPS:
        if args[0].endswith("load_students.py") and not (ROOT / "data/students/students.csv").exists():
            print(f"== {description}: skipped (no data/students/students.csv yet)")
            continue
        print(f"== {description}", flush=True)
        # Each script is the same one a person would run by hand, so there is one code path.
        subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
