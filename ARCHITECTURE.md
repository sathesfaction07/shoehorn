# Shoehorn — Technical Architecture

## Overview

Reads four formats into one model, then reports what the TARGET format cannot hold.

**Design principle:** "preserve structure" is a property of the target's GRAMMAR, not of the
parser. A perfect reader feeding a perfect tree into a pipe-table renderer still has to decide
what to put in a grid position the source never filled.

No model. The accuracy problem is grammar and arithmetic.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        CLI (shoehorn)                                 │
│                                                                              │
│  doctor     config, parsers, and WHICH MATRIX CLAIMS ARE WEAKER than the rest  │
│  matrix     what each target can express -- the ceiling, in one table          │
│  compare    all four targets over one corpus; the comparison IS the argument   │
│  report     per-document losses, and the SILENT ones                          │
│  check      EXIT 1 on a file no parser claims, or bytes someone chose to       │
│             discard. Does NOT fail on a merged cell, a heading skip or         │
│             mojibake -- those are properties of real documents, and a gate     │
│             that fires whenever somebody writes a spanning header in Word      │
│             gets switched off inside a week                                   │
│  collapse   the Catalan collapse, brute forced                                │
│  outline    one source, two readings, two trees that disagree                  │
│  table      the merged-cell dichotomy, both policies side by side              │
│  encoding   why errors='replace' is the lossy choice                          │
│  convert    emit one document, then say what the target could not hold         │
│  explain    one document against every target                                 │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             formats.py                                        │
│                          THE CEILING                                          │
│                                                                              │
│  Expressiveness  NATIVE / APPROXIMATE / ABSENT, per (target, feature).        │
│    A property of the GRAMMAR, so no parser, OCR service or model moves any     │
│    of it.                                                                     │
│                                                                              │
│  Capability  every non-NATIVE claim MUST carry a `reason`, enforced in the     │
│    constructor. A hardcoded table of assertions about file formats is how      │
│    folklore gets into a codebase, and these projects have caught six confident│
│    comments that turned out false.                                            │
│                                                                              │
│    The strongest claims are ARITHMETIC rather than cited:                      │
│                                                                              │
│      A pipe row `| a | b |` holds exactly as many cells as it has             │
│      delimiters. So a table rendered as pipe rows must emit `cols` cells in    │
│      EVERY row. A cell spanning two columns is ONE VALUE OVER TWO POSITIONS,   │
│      so the renderer emits one cell (short row) or two (a value duplicated     │
│      or blanked). No third option, and no reference implementation needed.     │
│                                                                              │
│    from_grammar=False marks claims resting on IMPLEMENTATION behaviour.        │
│    `doctor` prints those separately so they do not sit in the same table       │
│    looking equally solid. Three of them cannot be verified here at all.        │
│                                                                              │
│  TARGETS   markdown  what people actually pick                                │
│            wiki      CAN express a merged cell: cell syntax carries HTML attrs │
│            json      the model itself -- LOSSLESS BY CONSTRUCTION, the control │
│            plain     the far end of the range                                 │
│                                                                              │
│  ceiling(target, census)  takes a feature count and a target NAME. That is     │
│    what makes it a ceiling rather than a result: available BEFORE a single     │
│    document is rendered. On the corpus it orders the targets                   │
│    ['json','wiki','markdown','plain'] -- exactly how the measured losses come  │
│    out, and a test asserts the two orderings agree.                           │
│                                                                              │
│  IMAGE_TEXT is ABSENT in EVERY target including the control, because it is a   │
│    property of the SOURCE: the content is pixels. A matrix that let json       │
│    rescue it would be claiming OCR this tool does not do.                     │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              tables.py                                        │
│                                                                              │
│  occupancy()  walks cells onto a grid, HONOURING ROWSPAN -- each cell placed   │
│    at the first column of its row not already claimed from above, the way a    │
│    browser lays a table out. A colspan-only count gives rows of [2,1] for a    │
│    rowspan table and calls it RAGGED. It is rectangular.                      │
│                                                                              │
│      table        RxC  cells  positions  merged  shape                        │
│      colspan      2x2      3          4       1  rectangular                  │
│      rowspan      2x2      3          4       1  rectangular                  │
│      ragged       2x3      4          6       2  ragged                       │
│                                                                              │
│    The invariant: sum(colspan*rowspan) == rows*cols exactly when a grid        │
│    EXISTS. When it does not, no grid-based target can be faithful at all.     │
│                                                                              │
│  FlattenPolicy  the two options, wrong in OPPOSITE directions:                │
│                                                                              │
│      duplicate  Q1|Q1 / Jan|Feb   duplicated=1   distinct values 3            │
│      blank      Q1|   / Jan|Feb   blanked=1      distinct values 3            │
│                                                                              │
│    DUPLICATE asserts two columns were each labelled Q1. BLANK asserts one had  │
│    no label. The source said NEITHER -- and look at the last column: BOTH      │
│    LEAVE THE DISTINCT-VALUE SET UNCHANGED. That is why the loss is silent,     │
│    and it is arithmetic, not luck.                                            │
│                                                                              │
│  Flattened  three counters, and they are NOT the three first written. An       │
│    earlier version carried `dropped_cells` for "a cell that did not fit",      │
│    UNREACHABLE by construction since occupancy and flatten run the identical   │
│    placement walk -- 0 hits over 30,000 random tables. Meanwhile 26,174 of     │
│    those had HOLES, quietly filled with empty strings and never counted.       │
│    A field for an impossible failure made the model look more careful than it  │
│    was. `padded_positions` is the counter that was missing.                    │
│                                                                              │
│    The no-room branch now RAISES rather than counting: reaching it means the   │
│    two walks have diverged, which is a bug here rather than a property of the  │
│    table, and must not be reported as data loss.                              │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             outline.py                                        │
│                                                                              │
│  A source declares headings as a FLAT SEQUENCE OF NUMBERS. An outline is a     │
│  TREE. The map is where the wrongness lives, and it has two problems.         │
│                                                                              │
│  Reading  the skip is AMBIGUOUS, and neither option is called a fix:          │
│    PROMOTE   the h3 is the h1's child; skips vanish; declared numbers stop     │
│                meaning anything                                              │
│    IMPLICIT  a level is genuinely missing; depth matches the numbers; the      │
│                tree contains NODES THE DOCUMENT NEVER HAD                     │
│                                                                              │
│  collapse_census()  the map is NOT INJECTIVE, brute forced rather than         │
│    asserted:                                                                  │
│                                                                              │
│       n  sequences  promote  Catalan(n)  implicit  collapse                    │
│       1          6        1           1         6      6.0x                   │
│       6      46656      132         132     23525    353.5x                   │
│       7     279936      428         429    127547    654.1x  <- one short      │
│                                                                              │
│    EXACTLY Catalan(n) while n <= 6, because a promote-normalised outline IS    │
│    an ordered forest on n nodes and ordered forests are counted by Catalan     │
│    numbers. At n = 7 it falls short by EXACTLY ONE: the single depth-7 chain,  │
│    which six heading levels cannot express. Off by precisely one is what       │
│    confirms the explanation rather than merely fitting it.                     │
│                                                                              │
│    Concretely: [1,3] and [1,2] produce the SAME tree.                         │
│                                                                              │
│  Block.level therefore holds what the SOURCE declared and is NEVER rewritten   │
│  in place. A reading is applied at render time and named in the output.        │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             encoding.py                                       │
│                                                                              │
│  no_undecodable_bytes()  latin-1 rejects 0 of 256 byte values, so NO BYTE      │
│    SEQUENCE IS UNDECODABLE. Decoding.LOSSY is therefore UNREACHABLE through    │
│    decode_bytes with the default codec list -- verified over 4,000 random      │
│    byte strings. Which means every errors='replace' in a codebase is a         │
│    CHOICE to discard information, never a necessity forced by bad input.       │
│                                                                              │
│  compare_handlers()  the asymmetry, printed rather than described:             │
│                                                                              │
│      utf-8 + replace   'caf\ufffd'   recoverable False                        │
│      utf-8 + ignore    'caf'         recoverable False                        │
│      cp1252 (wrong)    'café'        recoverable True                         │
│                                                                              │
│    Being WRONG keeps every byte, because mis-decoding is invertible. Being     │
│    CAREFUL destroys them.                                                     │
│                                                                              │
│  Decoding  FOUR values, because "we decoded it" is not one claim:             │
│    CLEAN      valid UTF-8, no sign of a previous mis-decode                   │
│    MOJIBAKE   valid UTF-8 whose CONTENT was mis-decoded once; REVERSIBLE       │
│    AMBIGUOUS  4 codecs accepted the bytes and produced 3 DIFFERENT strings,    │
│                 and cp1252 was PREFERRED, NOT DETECTED                        │
│    LOSSY      unreachable by default; reachable only under a restricted list,  │
│                 so the branch is exercised rather than left as dead code       │
│                                                                              │
│  mojibake_lines()  scanned PER LINE, because the whole-text round trip needs   │
│    EVERY character to be mojibake. A document whose heading was mis-decoded    │
│    and whose next line was not fails at that byte: re-encoding a correct       │
│    U+00E9 as cp1252 gives 0xE9, not a valid UTF-8 lead byte. The partial case  │
│    is the common real one -- someone repaired one field -- and the obvious     │
│    test reports it CLEAN.                                                     │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    parse.py                        emit.py                    │
│                                                                              │
│  FOUR parsers, ONE model, so a later     census()  counts features; the input  │
│  difference in output is attributable      to `ceiling`. Merged cells counted  │
│  to the TARGET rather than the reader.     in GRID POSITIONS, because the      │
│  That is the experimental control the      position is what a target has to    │
│  whole project rests on.                   find something to put in.          │
│                                                                              │
│  html   BeautifulSoup + html5lib, which  Every emitter returns (text, losses). │
│    recovers malformed markup the way a     Returning only the text would make  │
│    BROWSER does. A strict parser would     the loss undiscoverable, which is   │
│    reject documents a reader can plainly   the failure this project is about.  │
│    see.                                                                       │
│                                          to_markdown  flattens tables, so it   │
│    Two bugs found by reading output:        reports INVENTED or DEGRADED       │
│    (1) `find_all` is RECURSIVE, so a     to_wiki      carries colspan/rowspan  │
│    nested table's rows were reported as     as HTML attributes: 0 losses on    │
│    the outer table's own -- a one-row       the same input                     │
│    table came out 3x2.                   to_json      the control              │
│    (2) a cell containing a nested table  to_plain     the far end              │
│    reported that table's text as its                                          │
│    OWN while the nested table was ALSO   Headings are emitted at their READ    │
│    emitted, so every value appeared        depth, not their declared level,    │
│    TWICE. A completeness check would       and the difference is REPORTED.     │
│    have seen MORE text after conversion    Emitting the declared level would   │
│    than the source had -- a gain, not      preserve the bytes and produce a    │
│    a bug.                                  document whose outline contradicts  │
│                                            its own numbering.                 │
│  docx  read from the XML via `grid_span`                                      │
│    and `vMerge`, NOT `row.cells`.                                             │
│    Verified: for a merged row,                                                │
│    [c.text for c in row.cells] returns                                        │
│    the value TWICE -- the same _tc                                            │
│    element yielded once per grid column,                                      │
│    so the LIBRARY applies the DUPLICATE                                       │
│    policy itself, silently.                                                   │
│                                                                              │
│    And `doc.paragraphs` EXCLUDES cell                                         │
│    text entirely: a document with one                                         │
│    2x2 table yields 3 paragraphs, none                                        │
│    of the 4 cell values, and logs a                                           │
│    confident "Read 3 paragraphs". That                                        │
│    is Certainty's read_docx_file.                                         │
│                                                                              │
│  wiki, markdown  hand-written, so a                                           │
│    round trip goes through the SAME                                           │
│    representation both ways. Reaching                                         │
│    for a third-party renderer for one                                         │
│    leg would make any round-trip result                                       │
│    a statement about that library.                                            │
│                                                                              │
│  has_embedded_text is DECLARED, never                                         │
│    detected. Stated because Headcount                                      │
│    shipped a "content-based format                                            │
│    sniffing" claim for metadata that was                                      │
│    likewise declared.                                                         │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             measure.py                                        │
│                                                                              │
│  The project brief asks ONE question with TWO halves: "did we extract ALL content      │
│  correctly AND preserve structure?" A checker for the first CANNOT SEE a       │
│  failure of the second.                                                       │
│                                                                              │
│  values_after: int | None   distinct values in the output AFTER RE-PARSING it. │
│    A REAL round trip, so the comparison is value-set against value-set.        │
│                                                                              │
│    An earlier version compared source VALUES against output LINES. A markdown  │
│    table row is one line holding three values, so every document with a table  │
│    produced a difference that meant nothing -- and the MERGED-CELL DOCUMENTS,  │
│    the entire point, were MISSING FROM THE LIST THEY SHOULD HAVE HEADED. It    │
│    reported a plausible boolean the whole time.                                │
│                                                                              │
│    None when the target has no parser here (json, plain), so no comparison is  │
│    possible. Those documents are `unmeasurable`, NOT proven quiet -- `all([])` │
│    being True is the same trap in a different costume.                        │
│                                                                              │
│  is_silent  losses occurred AND the round-tripped value set is identical.      │
│    13 of 23 documents for markdown. EVERY merged-cell document is among them,  │
│    and NONE of them is among wiki's, because wiki loses nothing on them.       │
│                                                                              │
│  fidelity_rate: float | None   None when the corpus has no structural          │
│    features at all, because 0/0 is not 100%. An unmeasured corpus has not      │
│    been preserved perfectly.                                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## The Findings

### One: the target is the ceiling

```
target       lost  fidelity  silent  by fidelity
json            1     99.0%       0  {'dropped': 1}
wiki            8     91.8%       6  {'degraded': 7, 'dropped': 1}
markdown       18     81.6%      13  {'invented': 9, 'degraded': 8, 'dropped': 1}
plain          73     25.5%       0  {'degraded': 46, 'dropped': 27}
```

Same parsers, same tree, same policy. `wiki` has **zero** invented instances where markdown has
nine. The ceiling computed from the census alone predicts this ordering exactly.

### Two: the loss is undetectable by a content check

`| Q1 | Q1 | Q2 |` in markdown against `! colspan="2" | Q1 !! Q2` in wiki — and **both merged-cell
policies leave the distinct-value set unchanged**, so a converter verifying its own work passes.

### Three: the outline collapse has a closed form

Catalan(n) exactly for n ≤ 6, short by exactly one at n = 7.

### Four: `errors="replace"` is never necessary

latin-1 rejects 0 of 256 bytes. The wrong answer is recoverable; the careful one is not.

---

## Data Flow

```
1.  shoehorn report
2.  route by EXTENSION (declared metadata, not sniffed); 23 documents, 4 formats
3.  decode: 20 clean, 2 mojibake (one whole-file, one partial), 1 ambiguous
      the ambiguous one: 4 codecs accepted it, 3 distinct strings, cp1252 PREFERRED
4.  parse into one Block tree per document
5.  census: 98 structural feature instances
6.  CEILING for markdown, from the census alone: 88 survive, 10 cannot be held
7.  emit, and collect a FeatureLoss per structural claim the target dropped
      invented 9, degraded 8, dropped 1 -> 18 lost, fidelity 81.6%
8.  RE-PARSE the output and compare value SETS
      13 of 23 identical despite losses -> SILENT
9.  exit 0: nothing unreadable, nothing discarded. A merged cell is not a defect
      anyone can fix at source, so it is reported and not gated on
```

---

## Testing

```bash
pytest                                                    # 132 tests, ~18s
pytest --cov=doc_consolidator --cov-report=term-missing    # 96%
```

| File | Covers |
|:--|:--|
| `conftest.py` | the corpus parsed once; the three canonical table shapes |
| `unit/test_core.py` | the ceiling; the pipe-row arithmetic **performed** rather than asserted; a reasonless claim rejected; implementation claims separated; the grid invariant; rowspan against the naive count; **both policies leaving the value set unchanged**; ragged padding; the placement walk never running out of room; `[1,3]`≡`[1,2]`; Catalan parametrised; **off by exactly one at n=7**; every model validator |
| `unit/test_encoding_parse_measure.py` | the three handlers; latin-1 rejecting nothing; `LOSSY` unreachable then reachable; partial mojibake; **python-docx duplicating a merged value**; **`doc.paragraphs` dropping every cell**; nested `<tr>` not leaking; no text duplication; the silent signature; `values_after` as a real round trip; `None` where no parser exists; corpus properties |
| `integration/test_cli.py` | all eleven commands, every exit-code reason, the JSON report's contents |

Nothing is mocked — several findings **are** the behaviour of python-docx and BeautifulSoup, and a
mock would assert my belief about them instead.

Four tests exist to stop the others being vacuous: every `Feature`, every `Fidelity` and three of
four `Decoding` values must occur, and `PLANTED` must match what is on disk. `LOSSY` is asserted
**absent**, because its unreachability is the finding.

---

## Configuration

`DC_`-prefixed environment variables or a `.env` file. No list-typed fields, since Pydantic
Settings parses those as JSON and `DC_X=a,b` would fail with a decode error reading like a bug in
the tool.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DC_", env_file=".env", extra="ignore")

    docs: Path = Path("data/docs")
    target: str = "markdown"          # what people pick, and what this tool has most to say about
    reading: Reading = Reading.PROMOTE
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE   # the status quo, and it invents content
    max_list_depth: int = Field(default=3, ge=1)
```

`policy` defaults to `DUPLICATE` because that is what python-docx does when you read `row.cells`,
so the shipped behaviour matches the status quo it is measuring. A defensible tool might refuse to
flatten at all.
