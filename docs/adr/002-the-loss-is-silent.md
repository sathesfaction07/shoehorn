# ADR 002: The loss is silent, because the checker for "all the content" cannot see it

## Status

Accepted

## Context

The project brief states the accuracy concern as one question: *"Did we extract ALL content correctly and
preserve structure?"*

That is two questions joined by an "and", and the second one fails in a way the first one's
checker cannot detect. A converter that verifies its work by comparing the values it read against
the values it wrote **passes** while emitting a table that asserts something the source never
said.

Three mechanisms produce that, and each is arithmetic rather than a matter of opinion.

## Decision

### One: a merged cell has no grid representation, and both repairs are wrong

A grid of R rows and C columns has R×C positions. A cell covering `colspan × rowspan` positions
is **one value**. So a table with a span has fewer cells than positions, and the difference is
countable:

```
table        RxC  cells  positions  merged  shape
colspan      2x2      3          4       1  rectangular
rowspan      2x2      3          4       1  rectangular
ragged       2x3      4          6       2  ragged
```

Writing that into a pipe grid has exactly two options, and they are wrong in **opposite**
directions:

```
duplicate  Q1|Q1 / Jan|Feb   duplicated=1   distinct values 3
blank      Q1|   / Jan|Feb   blanked=1      distinct values 3
```

`DUPLICATE` asserts two columns were each labelled Q1. `BLANK` asserts one column had no label.
The source said **neither** — and the critical line is the last column: **both leave the set of
distinct values unchanged.** That is why the loss is silent, and it is arithmetic, not luck.

The occupancy walk handles `rowspan` by placing each cell at the first column of its row not
already claimed from above — the way a browser lays a table out. A colspan-only count gives rows
of `[2, 1]` for the rowspan table above and calls it ragged; it is rectangular.

### Two: the flat-levels-to-outline map is not injective, and the collapse is Catalan(n)

A source declares headings as a flat sequence of numbers. An outline is a tree. Under the
`PROMOTE` reading, `[1, 3]` and `[1, 2]` produce the **same** tree, so the outline cannot tell you
what the document declared. Brute forced:

```
 n  sequences  promote  Catalan(n)  implicit  collapse
 1          6        1           1         6      6.0x
 2         36        2           2        26     18.0x
 3        216        5           5       150     43.2x
 4       1296       14          14       796     92.6x
 5       7776       42          42      4352    185.1x
 6      46656      132         132     23525    353.5x
 7     279936      428         429    127547    654.1x  <- one short
```

**Exactly Catalan(n) while n ≤ 6**, because a promote-normalised outline *is* an ordered forest on
n nodes and ordered forests are counted by Catalan numbers. At n = 7 it falls short by **exactly
one**: the single depth-7 chain, which six heading levels cannot express. Off by precisely one is
what confirms the explanation rather than merely fitting it.

`Reading` has two values and neither is called a fix, because neither is one:

| reading | keeps | pays |
|:--|:--|:--|
| `PROMOTE` | the tree shallow and honest about nesting | the declared numbers mean nothing |
| `IMPLICIT` | the declared numbers (injective at n=1) | invents nodes the document never had |

`Block.level` therefore holds what the **source** declared and is never rewritten in place; a
reading is applied at render time and named in the output.

### Three: `errors="replace"` is a choice, and it is the only irreversible one

```
handler           result          recoverable
utf-8 + replace   'caf\ufffd'     False
utf-8 + ignore    'caf'           False
cp1252 (wrong)    'café'          True
```

Being **wrong** keeps every byte, because mis-decoding is invertible. Being **careful** destroys
them. And the stronger form:

> latin-1 rejects **0 of 256** byte values, so no byte sequence is undecodable. `Decoding.LOSSY`
> is unreachable through `decode_bytes` with the default codec list — verified over 4,000 random
> byte strings.

So every `errors="replace"` in a codebase is a decision to discard information that could have
been kept. The sibling projects contain one: Certainty's `read_text_file`.

`Decoding` has four values because "we decoded it" is not one claim. `AMBIGUOUS` records that four
codecs accepted the bytes and produced **three different strings**, and that cp1252 was
**preferred, not detected**.

### `is_silent` is measured by a real round trip, not a proxy

The output is re-parsed through the target's own parser and the **value sets** are compared. On
the corpus, **13 of 23 documents** lose structure for markdown while that comparison sees nothing,
and every one of the six merged-cell documents is among them. None of them is among wiki's six,
because wiki loses nothing on them.

Where no parser exists — `json`, `plain` — `values_after` is `None` and the document is counted as
`unmeasurable` rather than proven quiet. `all([])` being True is the same trap in a different
costume.

## Validation

- `TestAMergedCellHasNoGridRepresentation` — the invariant; rowspan against the naive count; the
  dichotomy; **both policies leaving the value set unchanged**; ragged padding; the placement walk
  never running out of room
- `TestTheOutlineMapIsNotInjective` — `[1,3]` and `[1,2]` colliding; the readings disagreeing;
  Catalan for n ≤ 6 parametrised; the off-by-exactly-one at n = 7; declared levels untouched
- `TestTheSafeLookingHandlerIsTheLossyOne` — the three handlers; latin-1 rejecting nothing;
  `LOSSY` unreachable by default and reachable under a restricted list; partial mojibake
- `TestTheTwoQuestionsComeApart` — every merged-cell document silent for markdown and none for
  wiki; `values_after` being a round trip; `None` where no parser exists
- `setup.sh` and CI re-derive all of it

## Consequences

**Good**

- The silent case has a name, a count and a mechanism, and the mechanism is arithmetic
- Both merged-cell repairs are available and neither is presented as correct
- The outline collapse has a closed form, so "the outline is lossy" is quantified
- A refused measurement is never reported as a clean one

**Bad**

- **`is_silent` depends on my own parsers.** The round trip goes out through my emitter and back
  through my reader, so a value my markdown parser cannot read would show as a difference that a
  real toolchain would not see, and vice versa. It measures *this pair*, not markdown
- **`DUPLICATE` is the default**, which means the shipped behaviour is the one that invents
  content. It was chosen because it is what python-docx does when you read `row.cells`, so it is
  the status quo — but a defensible tool might refuse to flatten at all
- The Catalan result is **elegant and of limited practical use**. Knowing the collapse is 353× at
  six headings does not tell a specific team whether their specific outline is wrong
- `mojibake_lines` scans **per line**, which is a heuristic granularity. A document mis-decoded in
  the middle of a line is still missed, and the marker list that gates the round trip is
  hand-written and Western-centric — Cyrillic and CJK mojibake will often not match it
- **The corpus is mine and it is small.** 23 documents chosen to contain the cases the tool
  reports. "13 of 23 are silent" is a fact about this corpus and not an estimate for anyone's
  document set
- `Feature.FOOTNOTE` is never produced by any parser, so every claim about it is **untested**. The
  corpus-property test explicitly allows this rather than pretending otherwise

**Neutral**

- The encoding finding is the same shape as Doubletake's ambiguous dates — a loud failure is
  safer than a quiet success — and this says so rather than presenting it as new. What is
  different: here the competing readings are **countable** and the damage is **reversible**
- python-docx returning the same `_tc` twice for a merged row is the DUPLICATE policy applied by
  the library, silently. That is not a criticism of it; the XML carries the truth in `grid_span`
  and `vMerge`, and this project reads that instead
