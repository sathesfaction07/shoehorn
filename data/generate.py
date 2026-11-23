"""Build the corpus. Deterministic -- no randomness, so the reported figures are stable.

Every document plants something specific. The list is in `PLANTED` at the bottom and a test
asserts each one is actually reachable, because a corpus that quietly stops containing an
edge case turns every assertion about that case into a tautology.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
DOCS = HERE / "docs"


def write(name: str, text: str, encoding: str = "utf-8") -> None:
    (DOCS / name).write_bytes(text.encode(encoding))


def write_bytes(name: str, raw: bytes) -> None:
    (DOCS / name).write_bytes(raw)


# --------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------

def html_docs() -> None:
    # A clean, well-formed document. The control: nothing here should be reported lost by
    # any target except plain.
    write("h01-clean.html", """<!doctype html>
<html><body>
<h1>Returns Policy</h1>
<p>This page explains how returns are handled.</p>
<h2>Eligibility</h2>
<p>Most items may be returned within thirty days.</p>
<h2>Exceptions</h2>
<p>Perishable goods are excluded.</p>
</body></html>
""")

    # The heading skip: h1 then h3, no h2. Both readings are defensible and they disagree.
    write("h02-skip.html", """<!doctype html>
<html><body>
<h1>Shipping</h1>
<h3>Domestic</h3>
<p>Two to five working days.</p>
<h3>International</h3>
<p>Seven to twenty-one working days.</p>
<h2>Tracking</h2>
<p>A number is issued on dispatch.</p>
</body></html>
""")

    # A document that starts at h3. The same ambiguity, in a place nobody looks.
    write("h03-starts-deep.html", """<!doctype html>
<html><body>
<h3>Appendix C: Tariff Codes</h3>
<p>Extracted from a longer document.</p>
<h4>Sub-heading</h4>
<p>Detail.</p>
</body></html>
""")

    # The merged cell. A colspan=2 header over two columns: three cells, four positions.
    write("h04-merged.html", """<!doctype html>
<html><body>
<h1>Quarterly Volumes</h1>
<table>
  <tr><th colspan="2">Q1</th><th>Q2</th></tr>
  <tr><td>Jan</td><td>Feb</td><td>Apr</td></tr>
  <tr><td>1200</td><td>1100</td><td>1400</td></tr>
</table>
</body></html>
""")

    # rowspan, which the naive colspan-sum would call ragged.
    write("h05-rowspan.html", """<!doctype html>
<html><body>
<h1>Regional Contacts</h1>
<table>
  <tr><td rowspan="2">EMEA</td><td>London</td></tr>
  <tr><td>Berlin</td></tr>
  <tr><td>APAC</td><td>Tokyo</td></tr>
</table>
</body></html>
""")

    # A genuinely ragged table: the first row declares one column, the second declares three.
    # No grid exists, so ANY grid target must pad or discard.
    write("h06-ragged.html", """<!doctype html>
<html><body>
<h1>Notes</h1>
<table>
  <tr><td>Summary</td></tr>
  <tr><td>a</td><td>b</td><td>c</td></tr>
</table>
</body></html>
""")

    # A table inside a table.
    write("h07-nested-table.html", """<!doctype html>
<html><body>
<h1>Bundle Contents</h1>
<table>
  <tr><td>Kit A</td><td>
    <table><tr><td>bolt</td><td>x4</td></tr><tr><td>nut</td><td>x4</td></tr></table>
  </td></tr>
</table>
</body></html>
""")

    # Nested lists, and a table inside a list item.
    write("h08-nested-list.html", """<!doctype html>
<html><body>
<h1>Onboarding</h1>
<ul>
  <li>Prepare documents
    <ul><li>Photo identification</li><li>Proof of address</li></ul>
  </li>
  <li>Submit the form
    <table><tr><td>Field</td><td>Required</td></tr><tr><td>Name</td><td>yes</td></tr></table>
  </li>
</ul>
</body></html>
""")

    # An image declared to contain text. The declaration is metadata, not detection.
    write("h09-image-text.html", """<!doctype html>
<html><body>
<h1>Label Requirements</h1>
<p>The approved layout is shown below.</p>
<img src="label-spec.png" alt="Label layout" data-contains-text="true">
<img src="divider.png" alt="">
</body></html>
""")

    # Malformed markup: unclosed tags, a table row outside a table. html5lib recovers this
    # the way a browser does, which is the point of choosing it.
    write("h10-malformed.html", """<!doctype html>
<html><body>
<h1>Draft Notes
<p>First paragraph
<p>Second paragraph</p>
<table><tr><td>orphan
</body></html>
""")

    # PARTIAL mojibake: the heading was mis-decoded and the next line was not. This is the
    # common real case -- someone repaired one field -- and it defeats a whole-text round
    # trip, because re-encoding the correct 'e-acute' as cp1252 gives 0xE9, which is not a
    # valid UTF-8 lead byte. Detected only by scanning line by line.
    broken = "Café Münster — naïve résumé".encode().decode("cp1252")
    write("h11-mojibake.html", f"""<!doctype html>
<html><body>
<h1>Supplier: {broken}</h1>
<p>Contact: Jean-Léon Rousseau</p>
</body></html>
""")

    # WHOLE-file mojibake, so the simple round trip succeeds on it. Both cases are needed:
    # without this one the MOJIBAKE verdict would only ever be reached by the partial path.
    every_line = "\n".join(
        line.encode("utf-8").decode("cp1252")
        for line in (
            "<!doctype html>",
            "<html><body>",
            "<h1>Fournisseur: Café Münster</h1>",
            "<p>Décision reportée — révision nécessaire.</p>",
            "</body></html>",
        )
    )
    write("h13-mojibake-whole.html", every_line + "\n")

    # Not valid UTF-8 at all: cp1252 bytes on disk. Several codecs accept these and
    # disagree, so the decode is a preference rather than a detection.
    write_bytes(
        "h12-cp1252.html",
        "<!doctype html>\n<html><body>\n<h1>Réunion Réglementaire</h1>\n"
        "<p>Coût estimé: 1\u00a0200\u00a0€ — décision reportée.</p>\n"
        "</body></html>\n".encode("cp1252"),
    )


# --------------------------------------------------------------------------------------
# Wiki
# --------------------------------------------------------------------------------------

def wiki_docs() -> None:
    write("w01-clean.wiki", """= Escalation Runbook =
This page describes the escalation path.
== Severity 1 ==
Page the duty engineer immediately.
== Severity 2 ==
Raise a ticket before the end of the working day.
""")

    # A merged cell in a format that CAN hold one. Same feature as h04, different fate.
    write("w02-merged.wiki", """= Coverage Matrix =
{|
! colspan="2" | Business hours !! Out of hours
|-
| Weekday || Weekend || On call
|-
| 09:00-17:00 || closed || rota
|}
""")

    write("w03-skip.wiki", """= Product Taxonomy =
==== Level four, straight after level one ====
The intervening levels were never written.
== Level two ==
Arrives later.
""")

    write("w04-lists.wiki", """= Checklist =
* Confirm the order
** Check the address
** Check the payment
* Dispatch
# First numbered
# Second numbered
""")


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------

def markdown_docs() -> None:
    write("m01-clean.md", """# Incident Review

A short summary of the incident.

## Timeline

- Detected at 09:12
- Mitigated at 09:40

## Follow-up

Owner assigned.
""")

    write("m02-table.md", """# Rate Card

| Region | Standard | Express |
| --- | --- | --- |
| UK | 3.99 | 7.99 |
| EU | 5.99 | 11.99 |

Prices exclude tax.
""")

    write("m03-code.md", """# Configuration

Set the retry budget:

```
retries: 3
backoff: exponential
```

> Changing this affects every consumer.
""")


# --------------------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------------------

def docx_docs() -> None:
    from docx import Document as DocxDocument

    # A document whose table would be INVISIBLE to a paragraphs-only reader, and whose
    # merged header a `row.cells` reader would silently duplicate.
    doc = DocxDocument()
    doc.add_heading("Warehouse Capacity", level=1)
    doc.add_paragraph("Figures are indicative.")
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "Northern sites"
    table.cell(0, 1).text = ""
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 2).text = "Southern"
    for col, value in enumerate(("Leeds", "York", "Bristol")):
        table.cell(1, col).text = value
    for col, value in enumerate(("4200", "3100", "5000")):
        table.cell(2, col).text = value
    doc.add_paragraph("Reviewed quarterly.")
    doc.save(DOCS / "d01-merged.docx")

    # Heading skip plus both list flavours.
    doc = DocxDocument()
    doc.add_heading("Supplier Audit", level=1)
    doc.add_heading("Findings", level=3)
    doc.add_paragraph("Two minor observations.", style="List Bullet")
    doc.add_paragraph("One recommendation.", style="List Bullet")
    doc.add_heading("Actions", level=2)
    doc.add_paragraph("Update the checklist.", style="List Number")
    doc.add_paragraph("Re-audit in six months.", style="List Number")
    doc.save(DOCS / "d02-skip.docx")

    # A vertical merge, so the rowspan path is exercised on real OOXML.
    doc = DocxDocument()
    doc.add_heading("Shift Rota", level=1)
    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Early"
    table.cell(0, 1).text = "Ali"
    table.cell(1, 1).text = "Bea"
    table.cell(0, 0).merge(table.cell(1, 0))
    table.cell(2, 0).text = "Late"
    table.cell(2, 1).text = "Cal"
    doc.save(DOCS / "d03-rowspan.docx")


PLANTED = {
    "h01-clean.html": "a clean control document",
    "h02-skip.html": "h1 -> h3, a level skip mid-document",
    "h03-starts-deep.html": "first heading is h3, so the skip is at the start",
    "h04-merged.html": "colspan=2: three cells over four grid positions",
    "h05-rowspan.html": "rowspan=2, which a colspan-only count calls ragged",
    "h06-ragged.html": "1 column then 3: no grid exists at all",
    "h07-nested-table.html": "a table inside a table cell",
    "h08-nested-list.html": "a nested list, and a table inside a list item",
    "h09-image-text.html": "an image DECLARED to contain text, and one that is not",
    "h10-malformed.html": "unclosed tags recovered the way a browser would",
    "h11-mojibake.html": "PARTIAL mojibake: 1 line of 5, invisible to a whole-text check",
    "h13-mojibake-whole.html": "every line mojibake, so the simple round trip finds it",
    "h12-cp1252.html": "not UTF-8; several codecs accept it and disagree",
    "w01-clean.wiki": "a clean wiki control",
    "w02-merged.wiki": "a merged cell in a format that CAN express one",
    "w03-skip.wiki": "h1 -> h4, a two-level skip",
    "w04-lists.wiki": "nested and ordered wiki lists",
    "m01-clean.md": "a clean markdown control",
    "m02-table.md": "a plain rectangular pipe table",
    "m03-code.md": "a fenced code block and a blockquote",
    "d01-merged.docx": "a DOCX table invisible to a paragraphs-only reader",
    "d02-skip.docx": "DOCX heading styles with a skip, plus both list styles",
    "d03-rowspan.docx": "a real OOXML vertical merge",
}


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for existing in DOCS.iterdir():
        if existing.is_file():
            existing.unlink()
    html_docs()
    wiki_docs()
    markdown_docs()
    docx_docs()

    written = {p.name for p in DOCS.iterdir() if p.is_file()}
    missing = set(PLANTED) - written
    extra = written - set(PLANTED)
    if missing or extra:
        raise SystemExit(f"corpus mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    print(f"wrote {len(written)} documents to {DOCS}")
    for name, note in PLANTED.items():
        print(f"  {name:24} {note}")


if __name__ == "__main__":
    main()
