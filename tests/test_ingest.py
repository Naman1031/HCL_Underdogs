"""
Tests for app/ingest.py chunking (spec F.4) [BRIEF R2, R11]: chunks follow
clause boundaries, so a citation names the clause and page that holds the text.
"""

from app import config
from app.ingest import chunk_pages, extract_pages


def test_chunks_start_at_clause_numbers_and_keep_their_page():
    pages = ["Preamble line about the rules.\n7.1 Fees are paid each semester before registration.\n"
             "7.2 A student needs 75% attendance to sit the end-term examination.",
             "R.1(B).22 Attendance below the minimum leads to detention in that subject."]
    chunks = chunk_pages(pages)
    by_text = {text: (page, section) for text, page, section in chunks}
    attendance = next(t for t in by_text if "75%" in t)
    detention = next(t for t in by_text if "detention" in t)
    assert by_text[detention] == (2, "R.1(B).22")
    assert by_text[attendance][0] == 1


def test_synthetic_circular_cites_clause_2_1_for_the_80_percent_rule():
    pages = extract_pages(config.DOCUMENTS_DIR / "ACAD-CIRC-2026-08.md")
    chunk = next(c for c in chunk_pages(pages) if "minimum attendance of 80%" in c[0])
    assert chunk[2] == "2.1"


def test_long_clause_is_split_with_overlap_and_keeps_its_section():
    pages = ["4.1 " + " ".join(f"word{i}" for i in range(400))]
    chunks = chunk_pages(pages)
    assert len(chunks) >= 2
    assert all(section == "4.1" for _text, _page, section in chunks)
    assert chunks[0][0].split()[-1] in chunks[1][0].split()  # overlap between windows


def test_repeated_pages_are_indexed_once():
    page = "5.1 Students must register for every course at the start of the semester."
    assert len(chunk_pages([page, page])) == 1


def test_table_numbers_are_not_clause_numbers():
    chunks = chunk_pages(["3.2 Fees are listed below.\n163.87 lakh total budget for the fee concession scheme"])
    assert all(section == "3.2" for _text, _page, section in chunks)


def test_scanned_page_without_text_gives_no_chunks():
    assert chunk_pages(["", "   "]) == []
