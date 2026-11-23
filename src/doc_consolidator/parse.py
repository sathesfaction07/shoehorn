"""Four parsers, one model.

Each produces the same `Document`, so that a later difference in output is attributable to
the TARGET rather than to the reader. That is the experimental control the whole project
rests on: if markdown loses a merged cell and json does not, and both were handed the same
tree by the same code, the loss is the format's.

Two notes on what these do NOT do.

**`has_embedded_text` is DECLARED, never detected.** Whether an image contains text is not
knowable without OCR, which this tool does not perform. HTML carries the declaration in a
`data-contains-text` attribute and the corpus sets it. This is stated because Headcount
shipped a claim of "content-based format sniffing" for metadata that was likewise declared,
and that entry had to be corrected later.

**DOCX tables are read from the XML, not from `row.cells`.** Verified: for a row whose two
cells are merged, `[c.text for c in row.cells]` returns the value TWICE -- the same `_tc`
object is yielded once per grid column, so the library silently applies the DUPLICATE policy
from tables.py. `tc.grid_span` and `tc.vMerge` carry the truth.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import Tag

from .encoding import decode_bytes
from .models import Block, Cell, Document

# --------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------

_HEADING = re.compile(r"^h([1-6])$")


def _own_text(node: Tag) -> str:
    """A node's text, excluding anything inside a nested table.

    Without this, a cell containing a nested table reports that table's text as its OWN,
    and the nested table is ALSO emitted as a child block -- so every value inside it
    appears twice in `text_content`. A content-completeness check would then see MORE text
    after conversion than the source contained, which reads as a gain rather than a bug.
    """
    parts = [
        s for s in node.find_all(string=True)
        if s.find_parent("table") is node.find_parent("table")
    ]
    return " ".join(" ".join(parts).split())


def _html_cells(row: Tag) -> tuple[Cell, ...]:
    out: list[Cell] = []
    for td in row.find_all(["td", "th"], recursive=False):
        out.append(
            Cell(
                text=_own_text(td),
                colspan=max(1, int(td.get("colspan", 1) or 1)),
                rowspan=max(1, int(td.get("rowspan", 1) or 1)),
                is_header=td.name == "th",
            )
        )
    return tuple(out)


def _html_block(node: Tag) -> Block | None:
    name = node.name or ""

    match = _HEADING.match(name)
    if match:
        return Block(
            kind="heading", level=int(match.group(1)), text=node.get_text(" ", strip=True)
        )

    if name == "p":
        text = node.get_text(" ", strip=True)
        return Block(kind="paragraph", text=text) if text else None

    if name in ("ul", "ol"):
        items: list[Block] = []
        for li in node.find_all("li", recursive=False):
            # Direct text of the item, excluding any nested list's text.
            own = "".join(
                part for part in li.find_all(string=True, recursive=False)
            ).strip()
            children: list[Block] = []
            for sub in li.find_all(["ul", "ol", "table"], recursive=False):
                built = _html_block(sub)
                if built is not None:
                    children.append(built)
            items.append(
                Block(kind="list_item", text=own or li.get_text(" ", strip=True),
                      children=tuple(children))
            )
        return Block(kind="list", ordered=name == "ol", children=tuple(items))

    if name == "table":
        rows: list[Block] = []
        # `find_all` is recursive, so an unfiltered search picks up a NESTED table's rows
        # and reports them as this table's own -- verified on the corpus, where a one-row
        # outer table came out 3x2. A row belongs to this table only if this table is its
        # nearest table ancestor.
        for tr in node.find_all("tr"):
            if tr.find_parent("table") is not node:
                continue
            nested: list[Block] = []
            for sub in tr.find_all("table"):
                if sub.find_parent("table") is not node:
                    continue
                built = _html_block(sub)
                if built is not None:
                    nested.append(built)
            rows.append(Block(kind="row", cells=_html_cells(tr), children=tuple(nested)))
        return Block(kind="table", children=tuple(rows))

    if name in ("pre", "code"):
        return Block(kind="code", text=node.get_text("", strip=False).strip())

    if name == "blockquote":
        return Block(kind="quote", text=node.get_text(" ", strip=True))

    if name == "img":
        declared = str(node.get("data-contains-text", "")).lower() in ("1", "true", "yes")
        return Block(
            kind="image",
            text=str(node.get("src", "")),
            alt_text=str(node.get("alt", "")),
            has_embedded_text=declared,
        )

    return None


def parse_html(raw: bytes, doc_id: str) -> Document:
    """Parse with html5lib, which recovers malformed markup the way a browser would.

    A strict parser would reject documents a reader can plainly see, and the question here
    is what a reader would get, not what a validator would say.
    """
    result = decode_bytes(raw)
    soup = BeautifulSoup(result.text, "html5lib")
    body = soup.body or soup

    blocks: list[Block] = []
    # Top-level only: nested lists and tables are collected by their parent, so walking
    # everything would emit them twice.
    for node in body.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "pre",
         "blockquote", "img"]
    ):
        if node.find_parent(["li", "td", "th"]) is not None:
            continue
        built = _html_block(node)
        if built is not None:
            blocks.append(built)

    return Document(
        doc_id=doc_id,
        source_format="html",
        blocks=tuple(blocks),
        encoding_note=result.detail if result.decoding.value != "clean" else "",
    )


# --------------------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------------------

_DOCX_HEADING = re.compile(r"^Heading (\d)$")


def _docx_table(tbl) -> Block:
    from docx.table import _Cell

    rows: list[Block] = []
    # vMerge='continue' rows carry no value of their own; the rowspan belongs to the
    # 'restart' cell above, and is recovered by counting continues in the same column.
    raw_rows: list[list[tuple[str, int, str | None]]] = []

    for row in tbl.rows:
        entry: list[tuple[str, int, str | None]] = []
        for tc in row._tr.tc_lst:
            entry.append((_Cell(tc, tbl).text, tc.grid_span or 1, tc.vMerge))
        raw_rows.append(entry)

    # Resolve rowspans: walk down, and for each 'restart' count the 'continue's below it in
    # the same grid column.
    for r, entry in enumerate(raw_rows):
        col = 0
        cells: list[Cell] = []
        for text, span, vmerge in entry:
            if vmerge == "continue":
                col += span
                continue
            rowspan = 1
            if vmerge == "restart":
                probe = r + 1
                while probe < len(raw_rows):
                    below = _column_state(raw_rows[probe], col)
                    if below != "continue":
                        break
                    rowspan += 1
                    probe += 1
            cells.append(Cell(text=text, colspan=span, rowspan=rowspan))
            col += span
        rows.append(Block(kind="row", cells=tuple(cells)))

    return Block(kind="table", children=tuple(rows))


def _column_state(entry: list[tuple[str, int, str | None]], target: int) -> str | None:
    """The vMerge state of whichever cell occupies grid column `target` in this row."""
    col = 0
    for _text, span, vmerge in entry:
        if col <= target < col + span:
            return vmerge
        col += span
    return None


def parse_docx(path: Path, doc_id: str) -> Document:
    """Read a DOCX in true body order, with tables read from the XML.

    `body.iterchildren()` interleaves `p` and `tbl` correctly. Reading `doc.paragraphs` and
    `doc.tables` separately loses the ordering, and reading only `doc.paragraphs` loses the
    tables entirely -- verified: a document with one 2x2 table yields 3 paragraphs and none
    of the 4 cell values, while logging a confident count of what it did read.
    """
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = DocxDocument(str(path))
    blocks: list[Block] = []
    open_list: list[Block] = []
    open_ordered = False

    def flush() -> None:
        nonlocal open_list, open_ordered
        if open_list:
            blocks.append(
                Block(kind="list", ordered=open_ordered, children=tuple(open_list))
            )
            open_list = []

    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name or ""
            heading = _DOCX_HEADING.match(style)
            if heading:
                flush()
                blocks.append(
                    Block(kind="heading", level=int(heading.group(1)), text=text)
                )
            elif style.startswith("List "):
                ordered = "Number" in style
                if open_list and ordered != open_ordered:
                    flush()
                open_ordered = ordered
                open_list.append(Block(kind="list_item", text=text))
            else:
                flush()
                blocks.append(Block(kind="paragraph", text=text))

        elif tag == "tbl":
            flush()
            blocks.append(_docx_table(Table(child, doc)))

    flush()
    return Document(doc_id=doc_id, source_format="docx", blocks=tuple(blocks))


# --------------------------------------------------------------------------------------
# Wiki (MediaWiki-flavoured)
# --------------------------------------------------------------------------------------

_WIKI_HEADING = re.compile(r"^(={1,6})\s*(.+?)\s*\1\s*$")
_WIKI_ATTR = re.compile(r'(colspan|rowspan)\s*=\s*"?(\d+)"?')


def _wiki_cell(chunk: str, is_header: bool) -> Cell:
    colspan = rowspan = 1
    text = chunk
    if "|" in chunk:
        attrs, _, rest = chunk.partition("|")
        found = _WIKI_ATTR.findall(attrs)
        if found:
            for key, value in found:
                if key == "colspan":
                    colspan = max(1, int(value))
                else:
                    rowspan = max(1, int(value))
            text = rest
    return Cell(text=text.strip(), colspan=colspan, rowspan=rowspan, is_header=is_header)


def parse_wiki(raw: bytes, doc_id: str) -> Document:
    """Parse MediaWiki markup.

    Hand-written because there is no small, well-maintained MediaWiki parser and the subset
    that matters here -- headings, lists, and tables WITH span attributes -- is small. The
    span attributes are the reason wiki is in this project at all: it can express a merged
    cell, and markdown cannot.
    """
    result = decode_bytes(raw)
    blocks: list[Block] = []
    lines = result.text.splitlines()

    i = 0
    pending_items: list[Block] = []
    pending_ordered = False

    def flush_list() -> None:
        nonlocal pending_items
        if pending_items:
            blocks.append(
                Block(kind="list", ordered=pending_ordered, children=tuple(pending_items))
            )
            pending_items = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        heading = _WIKI_HEADING.match(stripped)
        if heading:
            flush_list()
            blocks.append(
                Block(kind="heading", level=len(heading.group(1)), text=heading.group(2))
            )
            i += 1
            continue

        if stripped.startswith("{|"):
            flush_list()
            rows: list[Block] = []
            current: list[Cell] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("|}"):
                cell_line = lines[i].strip()
                if cell_line.startswith("|-"):
                    if current:
                        rows.append(Block(kind="row", cells=tuple(current)))
                        current = []
                elif cell_line.startswith("!"):
                    for chunk in cell_line[1:].split("!!"):
                        current.append(_wiki_cell(chunk, True))
                elif cell_line.startswith("|"):
                    for chunk in cell_line[1:].split("||"):
                        current.append(_wiki_cell(chunk, False))
                i += 1
            if current:
                rows.append(Block(kind="row", cells=tuple(current)))
            blocks.append(Block(kind="table", children=tuple(rows)))
            i += 1
            continue

        if stripped.startswith(("*", "#")) and stripped[:1] in ("*", "#"):
            marker = stripped[0]
            depth = len(stripped) - len(stripped.lstrip(marker))
            text = stripped[depth:].strip()
            ordered = marker == "#"
            if pending_items and ordered != pending_ordered:
                flush_list()
            pending_ordered = ordered
            item = Block(kind="list_item", text=text)
            if depth > 1 and pending_items:
                parent = pending_items[-1]
                pending_items[-1] = parent.model_copy(
                    update={
                        "children": (
                            *parent.children,
                            Block(kind="list", ordered=ordered, children=(item,)),
                        )
                    }
                )
            else:
                pending_items.append(item)
            i += 1
            continue

        if stripped:
            flush_list()
            blocks.append(Block(kind="paragraph", text=stripped))
        else:
            flush_list()
        i += 1

    flush_list()
    return Document(
        doc_id=doc_id,
        source_format="wiki",
        blocks=tuple(blocks),
        encoding_note=result.detail if result.decoding.value != "clean" else "",
    )


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_ITEM = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_MD_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def parse_markdown(raw: bytes, doc_id: str) -> Document:
    """Parse the markdown subset this project also emits.

    Hand-written for the same reason as the wiki parser, plus one that matters more: a
    round trip has to go through the SAME representation in both directions, and reaching
    for a third-party renderer for one leg would make any round-trip result a statement
    about that library instead of about the format.
    """
    result = decode_bytes(raw)
    blocks: list[Block] = []
    lines = result.text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        heading = _MD_HEADING.match(line)
        if heading:
            blocks.append(
                Block(kind="heading", level=len(heading.group(1)),
                      text=heading.group(2).strip())
            )
            i += 1
            continue

        if stripped.startswith("```"):
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block(kind="code", text="\n".join(body)))
            continue

        if stripped.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(Block(kind="quote", text=" ".join(body)))
            continue

        if stripped.startswith("|"):
            rows: list[Block] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_line = lines[i].strip()
                if not _MD_DIVIDER.match(row_line):
                    parts = [p.strip() for p in row_line.strip("|").split("|")]
                    rows.append(
                        Block(kind="row", cells=tuple(Cell(text=p) for p in parts))
                    )
                i += 1
            if rows:
                blocks.append(Block(kind="table", children=tuple(rows)))
            continue

        item = _MD_ITEM.match(line)
        if item:
            items: list[Block] = []
            ordered = item.group(2) not in ("-", "*", "+")
            while i < len(lines):
                nxt = _MD_ITEM.match(lines[i])
                if not nxt:
                    break
                indent = len(nxt.group(1))
                node = Block(kind="list_item", text=nxt.group(3).strip())
                if indent >= 2 and items:
                    parent = items[-1]
                    items[-1] = parent.model_copy(
                        update={
                            "children": (
                                *parent.children,
                                Block(kind="list", ordered=ordered, children=(node,)),
                            )
                        }
                    )
                else:
                    items.append(node)
                i += 1
            blocks.append(Block(kind="list", ordered=ordered, children=tuple(items)))
            continue

        if stripped:
            blocks.append(Block(kind="paragraph", text=stripped))
        i += 1

    return Document(
        doc_id=doc_id,
        source_format="markdown",
        blocks=tuple(blocks),
        encoding_note=result.detail if result.decoding.value != "clean" else "",
    )


PARSERS = {
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".wiki": "wiki",
    ".md": "markdown",
}


def parse_file(path: Path) -> Document:
    """Route by extension, which is DECLARED metadata and not sniffed from content.

    Said plainly because the distinction has bitten this portfolio before: routing on an
    extension is a decision to trust the filename, and a `.html` file containing DOCX bytes
    would be parsed as HTML and produce a confident, empty result.
    """
    kind = PARSERS.get(path.suffix.lower())
    if kind is None:
        raise ValueError(
            f"no parser for {path.suffix!r}; known: {sorted(PARSERS)}"
        )
    doc_id = path.stem
    if kind == "docx":
        return parse_docx(path, doc_id)
    raw = path.read_bytes()
    if kind == "html":
        return parse_html(raw, doc_id)
    if kind == "wiki":
        return parse_wiki(raw, doc_id)
    return parse_markdown(raw, doc_id)
