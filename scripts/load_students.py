"""
Loads a folder of Annex C student CSVs into SQLite (spec F.6, G.3) [BRIEF Annex C].
The judges use this for their own students (S9000+), so it accepts any folder and
skips any of the four CSVs that is missing. It runs the generic checks from
validate_students.py first and loads nothing if one fails. Rows with an existing
key are replaced (upsert), so loading the same folder twice is safe.
Usage: python scripts/load_students.py --dir test_students/
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # lets `python scripts/...` import app

from app import config, db  # noqa: E402
from scripts.validate_students import FILES, validate  # noqa: E402

# Load order matters: attendance and results reference students and courses.
TABLES = [  # (csv file, table, key columns)
    ("courses.csv", "courses", ["course_code"]),
    ("students.csv", "students", ["student_id"]),
    ("attendance.csv", "attendance", ["student_id", "course_code"]),
    ("results.csv", "results", ["student_id", "course_code", "exam_session", "exam_type"]),
]


def upsert(conn, table: str, keys: list[str], rows: list) -> None:
    columns = list(type(rows[0]).model_fields)
    placeholders = ", ".join("?" for _ in columns)
    values = [tuple(row.model_dump().values()) for row in rows]
    if table == "results":
        # results has no primary key in Annex C, so replace by deleting the same key first.
        where = " AND ".join(f"{k} = ?" for k in keys)
        conn.executemany(f"DELETE FROM results WHERE {where}", [tuple(getattr(r, k) for k in keys) for r in rows])
        conn.executemany(f"INSERT INTO results ({', '.join(columns)}) VALUES ({placeholders})", values)
        return
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in keys)
    conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
                     f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}", values)


def load(folder: Path, as_of: date) -> dict[str, int]:
    """Validates, then upserts every CSV present in one transaction. Returns rows loaded per file."""
    if not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")
    if not any((folder / name).exists() for name in FILES):
        raise SystemExit(f"No Annex C CSVs ({', '.join(FILES)}) in {folder}")
    db.init_db()
    known_students = {r["student_id"]: r for r in db.query("SELECT student_id, programme, batch_year FROM students")}
    known_courses = {r["course_code"]: r["programme"] for r in db.query("SELECT course_code, programme FROM courses")}
    rows, errors, report = validate(folder, False, as_of, known_students, known_courses)
    print("\n".join(report))
    if errors:
        raise SystemExit("Nothing loaded: fix the errors above first.")
    conn = db.connect()
    try:
        for name, table, keys in TABLES:
            if rows.get(name):
                upsert(conn, table, keys, rows[name])
        conn.commit()
    finally:
        conn.close()
    return {name: len(rows[name]) for name, _table, _keys in TABLES if name in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=config.STUDENTS_DIR)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="date the pass mark is resolved for")
    args = parser.parse_args()
    loaded = load(args.dir, date.fromisoformat(args.as_of))
    print("Loaded: " + ", ".join(f"{name} {n} rows" for name, n in loaded.items()))


if __name__ == "__main__":
    main()
