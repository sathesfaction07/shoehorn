"""Shared fixtures.

Nothing is mocked. The corpus is real files on disk, python-docx reads real OOXML, and
BeautifulSoup parses real markup -- because most of the findings here ARE the behaviour of
those libraries, and a mock would assert my belief about them rather than their behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doc_consolidator.models import Cell
from doc_consolidator.parse import parse_file

DOCS = Path(__file__).resolve().parents[1] / "data" / "docs"


@pytest.fixture(scope="session")
def docs_dir() -> Path:
    if not DOCS.exists() or not any(DOCS.iterdir()):
        pytest.fail(
            f"corpus missing at {DOCS}; run `python data/generate.py`"
        )
    return DOCS


@pytest.fixture(scope="session")
def corpus(docs_dir: Path) -> dict:
    """Every document, parsed once."""
    return {p.stem: parse_file(p) for p in sorted(docs_dir.iterdir()) if p.is_file()}


def cell(text: str, colspan: int = 1, rowspan: int = 1, header: bool = False) -> Cell:
    return Cell(text=text, colspan=colspan, rowspan=rowspan, is_header=header)


@pytest.fixture(scope="session")
def colspan_table() -> tuple:
    """Three cells over four grid positions. The canonical merged-cell case."""
    return ((cell("Q1", colspan=2, header=True),), (cell("Jan"), cell("Feb")))


@pytest.fixture(scope="session")
def rowspan_table() -> tuple:
    """A cell spanning downward, which a colspan-only count calls ragged."""
    return ((cell("EMEA", rowspan=2), cell("London")), (cell("Berlin"),))


@pytest.fixture(scope="session")
def ragged_table() -> tuple:
    """One column then three. No grid exists for this at all."""
    return ((cell("Summary"),), (cell("a"), cell("b"), cell("c")))
