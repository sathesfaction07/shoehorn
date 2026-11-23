# ADR 001: "Preserve structure" is a property of the target format, not of the parser

## Status

Accepted

## Context

The brief rates four approaches to this problem by parser quality — BeautifulSoup and friends
at "~90% (misses images-with-text, breaks on exotic formatting)", Docling at ~95%, cloud OCR at
"~99% on PDFs", a hybrid at ~97% — and concludes: *"Hybrid routing by format."*

Two things came out of checking that before building.

**The routing already exists.** Certainty dispatches on file extension, renders PDFs through
PyMuPDF and has a Textract backend. So the brief's headline recommendation is built, one
directory across.

**And it would not have helped.** Markdown has no construct for a merged table cell. No parser,
no layout model and no OCR service changes that, because it is a property of markdown's grammar.
A perfect reader feeding a perfect tree into a pipe-table renderer still has to decide what to
put in a grid position the source never filled.

So the brief measures the wrong axis. Parser quality is real and it is not the binding
constraint.

## Decision

### The capability matrix is the primary artefact, and every claim in it carries a reason

`Expressiveness` is three-valued — `NATIVE`, `APPROXIMATE`, `ABSENT` — per (target, feature).
A hardcoded table of assertions about file formats is exactly how folklore gets into a codebase,
and this portfolio has already caught six confident comments that turned out false. So:

- every non-`NATIVE` entry must carry a `reason`, enforced in the constructor
- `verify_claims()` re-derives the arithmetic ones at runtime
- `from_grammar=False` marks claims resting on *implementation* behaviour, and `doctor` prints
  those separately so they do not sit in the same table looking equally solid

The strongest claims are arithmetic rather than cited:

> A pipe row `| a | b |` holds exactly as many cells as it has delimiters. So a table rendered
> as pipe rows must emit `cols` cells in **every** row. A cell spanning two columns is **one
> value over two positions**, so the renderer must emit one cell (and the row is short) or two
> (and a value is duplicated or blanked). No reference implementation is needed to see that
> there is no third option.

### Four targets, two of them controls

| target | role |
|:--|:--|
| `markdown` | what people actually pick |
| `wiki` | can express a merged cell, because its cell syntax carries HTML attributes |
| `json` | the model itself — **lossless by construction** |
| `plain` | the far end of the range |

`json` is the experimental control. All four emitters are handed the same tree by the same
parsers with the same policy, so if json loses nothing and markdown loses a span, the loss
cannot be attributed to the reader. Measured on the corpus:

```
target       lost  fidelity  silent  by fidelity
json            1     99.0%       0  {'dropped': 1}
wiki            8     91.8%       6  {'degraded': 7, 'dropped': 1}
markdown       18     81.6%      13  {'invented': 9, 'degraded': 8, 'dropped': 1}
plain          73     25.5%       0  {'degraded': 46, 'dropped': 27}
```

`wiki` has **zero** invented instances where markdown has nine, on identical input.

### The ceiling is computed before any conversion runs

`ceiling(target, census)` takes a feature count and a target *name*. That is what makes it a
ceiling rather than a result: it is available before a single document is rendered, and no
change of parser moves it. On the corpus the ceiling orders the targets
`['json', 'wiki', 'markdown', 'plain']` — exactly how the measured losses come out, and a test
asserts the two orderings agree.

### `Fidelity` has four values because a bool collapses the two that matter

`INVENTED` and `DROPPED` are both "the target could not hold it", and they fail in **opposite
directions**: one adds content the source never had, the other removes content it did. A single
`lossy: bool` reports them identically. `DEGRADED` is the third case — every character survives
and a *relationship* does not.

### `image_text` is `ABSENT` in every target, including the lossless one

It is the only feature that is a property of the **source**: the content is pixels and the
source never provided it as text. A matrix that let json rescue it would be claiming OCR this
tool does not do. `has_embedded_text` is therefore **declared** metadata read from an attribute,
never inferred — stated plainly because Headcount shipped a claim of "content-based format
sniffing" for metadata that was likewise declared, and that entry had to be corrected later.

## Validation

- `TestTheTargetFormatIsTheCeiling` — the markdown/wiki split; the pipe-row arithmetic performed
  rather than asserted; every limited claim carrying a reason; a reasonless claim rejected;
  implementation claims separated from grammar ones; json lossless; no target claiming OCR;
  the ceiling computable from a census
- `TestTheTwoQuestionsComeApart` — the same tree to two targets; the ceiling ordering matching
  the result ordering; wiki's invented count being zero while markdown's is not
- `setup.sh` and CI re-derive the matrix, the arithmetic and the four-target comparison

## Consequences

**Good**

- The question changes from "which parser" to "which target", which is the one that decides the
  answer and is usually settled by habit
- A reader can see what a conversion will cost *before* running it
- `INVENTED` and `DROPPED` are visible as different problems
- No claim in the matrix is unfalsifiable, and the weaker ones are labelled

**Bad**

- **The matrix is hardcoded in Python.** Adding a target means editing source, which is the
  wrong shape for something that changes when a team adopts a new wiki
- Three claims rest on implementation behaviour rather than grammar and **cannot be verified
  here at all** — `table_in_list` for markdown and wiki, and markdown footnotes. They are
  labelled, which is honest and is not the same as being checked
- `markdown` means GFM-flavoured, which is a **choice about which markdown**. Strict CommonMark
  has no table construct at all, and the more generous reading was used because it makes the
  finding harder to reach rather than easier
- **`json` winning is a boring answer.** It is reported anyway, because a tool that steered a
  reader towards a prettier format knowing it drops content would be choosing presentation on
  their behalf. But nobody publishes a runbook as a JSON blob, so the useful comparison is
  markdown against wiki and the control mostly sits there being right
- The feature list is **mine**. Features were named at the granularity where these four formats
  differ, which is a defensible choice and also one that flatters the conclusion — a feature set
  chosen differently would produce different numbers
- Nothing here **fixes** anything. The remedies are outside the tool: publish to a format that
  can hold your content, or stop putting merged cells in source documents

**Neutral**

- This is the same *shape* as Kinship's finding that blocking sets a recall ceiling no matcher
  can exceed, and saying so is better than implying novelty. The difference is that blocking keys
  are a free choice while a publishing target usually is not — you often must publish to the wiki
- The cloud-OCR routing in the brief was declined rather than rebuilt, and the reason is
  duplication rather than disagreement: for a scanned PDF, Textract genuinely is the right answer
  and Certainty already calls it
