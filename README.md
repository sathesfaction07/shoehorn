# Shoehorn

Turning PDFs, Word files and web pages into Markdown looks like a parsing problem, so teams
shop for a better parser. The loss usually happens one step later: Markdown cannot express a
merged table cell, so no parser, layout model or OCR service can carry one across.
Shoehorn reads four input formats into one document model, then reports, feature by
feature, what the format you are writing *to* cannot hold.

Everything here is grammar and counting; there is no model to tune.

---

## Parser Accuracy Is the Wrong Axis

The requirements note this project started from rates four approaches by parser quality — BeautifulSoup at "~90%", Docling at ~95%,
cloud OCR at "~99% on PDFs" — and concludes *"hybrid routing by format."*

Checking that first produced two things:

**The routing already exists.** Certainty dispatches on extension, renders PDFs through
PyMuPDF and has a Textract backend. The headline recommendation is built, one directory across.

**And it would not have helped.** Markdown has no construct for a merged table cell. No parser,
no layout model and no OCR service changes that.

```
  feature              json  markdown     plain      wiki
  -------------------------------------------------------
  merged_cell           yes        NO        NO       yes
  nested_table          yes        NO        NO       yes
  table_in_list         yes    approx        NO    approx
  image_text             NO        NO        NO        NO
```

---

## The Arithmetic

A pipe row `| a | b |` holds exactly as many cells as it has delimiters. So a table rendered as
pipe rows must emit `cols` cells in **every** row. A cell spanning two columns is **one value over
two positions**, so the renderer must emit one cell (short row) or two (a value duplicated or
blanked). **No third option**, and it follows from the delimiters — no reference implementation
needed.

```
table        RxC  cells  positions  merged  shape
colspan      2x2      3          4       1  rectangular
rowspan      2x2      3          4       1  rectangular
ragged       2x3      4          6       2  ragged
```

`rowspan` is placed the way a browser lays a table out. A colspan-only count gives rows of
`[2, 1]` for that middle table and calls it ragged. It is rectangular.

---

## The Headline: Both Repairs Are Wrong, and Neither Is Detectable

```
duplicate  Q1|Q1 / Jan|Feb   duplicated=1   distinct values 3
blank      Q1|   / Jan|Feb   blanked=1      distinct values 3
```

`DUPLICATE` asserts two columns were each labelled Q1. `BLANK` asserts one column had no label.
The source said **neither** — and look at the last column: **both leave the set of distinct values
unchanged.**

So the spec's single question is really two, and the first one's checker cannot see the second
one's failure:

> **13 of 23 documents** lose structure for markdown while a round-tripped value-set comparison
> sees no difference at all. Every one of the six merged-cell documents is among them. **None** of
> them is among wiki's, because wiki loses nothing on them.

The same tree, two targets:

```
markdown  | Q1 | Q1 | Q2 |          1 loss: merged_cell/invented
wiki      ! colspan="2" | Q1 !! Q2  0 losses
```

Same parsers, same tree, same policy. **Only the target differs.**

---

## Four Targets, Two of Them Controls

```
target       lost  fidelity  silent  by fidelity
json            1     99.0%       0  {'dropped': 1}
wiki            8     91.8%       6  {'degraded': 7, 'dropped': 1}
markdown       18     81.6%      13  {'invented': 9, 'degraded': 8, 'dropped': 1}
plain          73     25.5%       0  {'degraded': 46, 'dropped': 27}
```

`json` is the experimental control: lossless by construction, so a loss elsewhere cannot be blamed
on the reader. `wiki` has **zero** invented instances where markdown has nine.

The **ceiling** — computed from the feature census and the target *name* alone, before any
conversion runs — orders the targets `['json', 'wiki', 'markdown', 'plain']`, exactly how the
measured losses come out. A test asserts the two orderings agree.

`Fidelity` has four values because a `lossy: bool` collapses the two that matter. **`INVENTED` and
`DROPPED` fail in opposite directions**: one adds content the source never had, the other removes
content it did.

---

## The Outline Collapse Is Catalan(n)

A source declares headings as a flat sequence of numbers. An outline is a tree. `[1, 3]` and
`[1, 2]` produce the **same** tree, so the outline cannot tell you what the document declared.

```
 n  sequences  promote  Catalan(n)  implicit  collapse
 1          6        1           1         6      6.0x
 3        216        5           5       150     43.2x
 6      46656      132         132     23525    353.5x
 7     279936      428         429    127547    654.1x  <- one short
```

**Exactly Catalan(n) while n ≤ 6**, because a promote-normalised outline *is* an ordered forest on
n nodes. At n = 7 it falls short by **exactly one**: the single depth-7 chain, which six heading
levels cannot express. Off by precisely one is what confirms the explanation rather than merely
fitting it.

Neither reading is a fix. `PROMOTE` discards the declared numbers; `IMPLICIT` keeps them and
invents nodes the document never contained. So `Block.level` holds what the source said and is
never rewritten in place.

---

## `errors="replace"` Is a Choice, and It Is the Only Irreversible One

```
handler           result       recoverable
utf-8 + replace   'caf\ufffd'  False
utf-8 + ignore    'caf'        False
cp1252 (wrong)    'café'       True
```

Being **wrong** keeps every byte, because mis-decoding is invertible. Being **careful** destroys
them. And the stronger form:

> latin-1 rejects **0 of 256** byte values, so **no byte sequence is undecodable**.
> `Decoding.LOSSY` is unreachable with the default codec list — verified over 4,000 random byte
> strings.

Every `errors="replace"` is therefore a decision to discard information that could have been kept.
The portfolio contains one: Certainty's `read_text_file`.

`AMBIGUOUS` records that four codecs accepted the same bytes and produced **three different
strings**, and that cp1252 was **preferred, not detected**.

### Partial mojibake defeats the obvious test

A document whose heading was mis-decoded and whose next line was not fails a whole-text round
trip: re-encoding a correct `é` as cp1252 gives `0xE9`, which is not a valid UTF-8 lead byte. So
the scan is per line, and the corpus carries both cases.

---

## Two Defects in Existing Portfolio Code, Verified

**Certainty's `read_docx_file` drops every table.** It does
`[p.text for p in doc.paragraphs]`, and `doc.paragraphs` excludes cell text entirely. On a
document with one 2×2 table it yields 3 paragraphs, none of the 4 cell values, and logs a
confident *"Read 3 paragraphs"*.

**And `[c.text for c in row.cells]` silently duplicates a merged value.** python-docx yields the
same `_tc` element once per grid column, so it applies the DUPLICATE policy itself with no
indication. Not a criticism of the library — the XML carries the truth in `grid_span` and
`vMerge`, and this project reads that instead.

---

## Running

```bash
bash setup.sh                          # re-derives every finding above
source .venv/bin/activate

shoehorn doctor                # config, and which matrix claims are weaker
shoehorn matrix                # what each target can express
shoehorn compare               # all four targets, one corpus
shoehorn report                # per-document losses, and the silent ones
shoehorn check                 # exit 1 on what is fixable at source
shoehorn collapse              # the Catalan collapse, brute forced
shoehorn outline h02-skip      # one source, two readings, two trees
shoehorn table h04-merged      # the merged-cell dichotomy
shoehorn encoding              # why replace is the lossy choice
shoehorn convert h04-merged    # emit, then say what was lost
shoehorn explain h04-merged    # one document against every target
```

| Command | Exit |
|:--|:--|
| `check` | **1** on a file no parser claims, or bytes someone chose to discard |
| `report` | **1** if the corpus carries either of those |
| everything else | 0 |

`check` does **not** fail on a merged cell, a heading skip or mojibake. Those are properties of
real documents, and a gate that fires whenever somebody writes a spanning header in Word gets
switched off inside a week.

---

## Testing

```bash
pytest                                             # 132 tests, ~18s
pytest --cov=doc_consolidator --cov-report=term-missing   # 96%
```

Nothing is mocked. The corpus is real files, python-docx reads real OOXML, BeautifulSoup parses
real markup — because several of the findings **are** the behaviour of those libraries, and a mock
would assert my belief about them instead.

Four tests exist to stop the others being vacuous: every `Feature`, every `Fidelity` and three of
four `Decoding` values must occur in the corpus, and the `PLANTED` manifest must match what is on
disk. `LOSSY` is asserted **absent**, because its unreachability is the finding.

---

## Three Things I Got Wrong, Found by Reading Output

**A counter for an impossible failure, and none for the real one.** `Flattened` carried
`dropped_cells` for "a cell that did not fit" — unreachable by construction, since `occupancy` and
`flatten` run the identical placement walk. 0 hits over 30,000 random tables. Meanwhile 26,174 of
those 30,000 had **holes** that were quietly filled with empty strings and never counted. A field
for an impossible failure made the model look more careful than it was.

**`is_silent` compared incomparable quantities.** `values_before` counted distinct cell values;
`values_after` counted output **lines**. A markdown table row is one line holding three values, so
every document with a table produced a difference that meant nothing — and the merged-cell
documents, the entire point, were **missing from the list they should have headed**. Now a real
round trip through the target's own parser.

**Nested `<tr>` leaked into the outer table.** `find_all` is recursive, so a one-row table
containing a nested table came out `3x2`. Found by reading the parse table and noticing a number
that could not be right. The same pass caught nested-table text being counted twice, which would
have made a completeness check report *more* content after conversion than the source had.

---

## Scope: What This Deliberately Does Not Do

**Route PDFs to Textract or Document AI**, which the brief asks for. Certainty already does
it, and for a scanned PDF that genuinely is the right answer. Declined as duplication, not
disagreement.

**Deduplicate across sources**, also asked for. That is Kinship — normalisation, blocking,
clustering and cluster metrics — and rebuilding it here would be a worse copy.

**OCR images that contain text.** `has_embedded_text` is **declared** metadata, never inferred.
Said plainly because Headcount shipped a claim of "content-based format sniffing" for metadata
that was likewise declared, and that entry needed correcting later.

The diligence check found heading handling, `colspan`/`rowspan`, document outlines,
BeautifulSoup, wiki markup and mojibake detection **absent portfolio-wide** (0 files each).
Polarity builds a tree, but it is an AST for boolean expressions — so tree-building is a repeat
mechanism and is named as one. What is new is that this map is **not injective**.

---

## Tradeoffs

**`is_silent` depends on my own parsers.** The round trip goes out through my emitter and back
through my reader, so it measures *this pair*, not markdown.

**`DUPLICATE` is the default**, so the shipped behaviour is the one that invents content. Chosen
because it is what python-docx does — the status quo — but a defensible tool might refuse to
flatten at all.

**The corpus is mine and it is small.** 23 documents chosen to contain the cases the tool reports.
"13 of 23" is a fact about this corpus, not an estimate for anyone's document set.

**The matrix is hardcoded in Python**, and three of its claims rest on implementation behaviour
rather than grammar. They are labelled as weaker, which is honest and is not the same as checked.

**The Catalan result is elegant and of limited practical use.** Knowing the collapse is 353× at
six headings does not tell a team whether their outline is wrong.

**`mojibake_lines` scans per line**, and its marker list is Western-centric — Cyrillic and CJK
mojibake will often not match.

**`Feature.FOOTNOTE` is never produced by any parser**, so every claim about it is untested. The
corpus test allows this explicitly rather than pretending otherwise.

**Nothing here fixes anything.** Publish to a format that can hold your content, or stop putting
merged cells in source documents.

This is the same *shape* as Kinship's blocking ceiling — an upstream constraint no downstream
stage can exceed — and saying so beats implying novelty. The difference: blocking keys are a free
choice, and you often must publish to the wiki.

---

## Configuration

```bash
DC_DOCS=data/docs
DC_TARGET=markdown       # the one people pick, and the one this tool has most to say about
DC_READING=promote       # promote | implicit -- a reading, not a fix
DC_POLICY=duplicate      # duplicate | blank -- both wrong, differently
```

---

## Stack

| Concern | Choice |
|:--|:--|
| Language | Python 3.11+ |
| Models + config | Pydantic, Pydantic Settings |
| CLI | Click |
| HTML | BeautifulSoup + **html5lib**, which recovers malformed markup the way a browser does |
| DOCX | python-docx, read via `grid_span`/`vMerge` rather than `row.cells` |
| Wiki, Markdown | hand-written, so a round trip goes through one representation both ways |
| Output | markdown, wiki, JSON, plain text |
| Tests | pytest, Click's CliRunner |
| Models/AI | none, deliberately |

The corpus is deterministic via `data/generate.py`: 23 documents across four formats. Planted — a
mid-document heading skip, a document starting at `h3`, a `colspan`, a real OOXML `vMerge`, a
ragged table with no grid, a nested table, a table inside a list item, an image declared to
contain text, unclosed tags, whole-file mojibake, partial mojibake, and cp1252 bytes that four
codecs read three ways.
