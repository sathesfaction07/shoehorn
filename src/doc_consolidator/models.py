"""The document model, and the vocabulary for what a conversion did to it.

The central claim of this project is that "preserve structure" is not a property of the
parser. It is a property of the TARGET, and the model has to be able to say so -- which
means a conversion result cannot be a bool, and a feature cannot be a string.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Feature(StrEnum):
    """A structural feature a document can contain.

    These are the things that survive or do not survive a conversion. They are named at
    the granularity where formats actually DIFFER: every format here can hold a heading
    and a paragraph, and they diverge on merged cells, nesting depth and containment.
    """

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    NESTED_LIST = "nested_list"
    TABLE = "table"
    MERGED_CELL = "merged_cell"
    NESTED_TABLE = "nested_table"
    TABLE_IN_LIST = "table_in_list"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"
    IMAGE = "image"
    IMAGE_TEXT = "image_text"
    FOOTNOTE = "footnote"


class Fidelity(StrEnum):
    """What happened to a feature on the way to the target format.

    A bool cannot express this, and the two interesting values are the ones a bool
    collapses. INVENTED and DROPPED are both "the target could not hold it", and they
    fail in OPPOSITE directions -- one adds content that was never in the source, the
    other removes content that was. A single `lossy: bool` reports them identically.
    """

    EXACT = "exact"
    """Expressible in the target, and emitted without weakening."""

    DEGRADED = "degraded"
    """Expressible only by weakening it -- nesting flattened, a level clamped. The
    content survives and the relationship between parts does not."""

    INVENTED = "invented"
    """The target could not hold it, and the repair ADDED content. A merged cell
    flattened to a grid duplicates its value into cells that never existed."""

    DROPPED = "dropped"
    """The target could not hold it, and the repair REMOVED content."""


class Expressiveness(StrEnum):
    """Whether a target format can hold a feature at all.

    Determined by the format's grammar, not by any parser. This is the ceiling.
    """

    NATIVE = "native"
    """The format has a construct for it."""

    APPROXIMATE = "approximate"
    """The format can carry the content but not the relationship."""

    ABSENT = "absent"
    """The format has no construct for it. No parser can change this."""


class Cell(BaseModel):
    """One table cell, which may span.

    `colspan`/`rowspan` are the whole difficulty: a grid is rows x cols cells, and a
    table with a span has FEWER cells than that. See tables.py for the invariant.
    """

    model_config = ConfigDict(frozen=True)

    text: str = ""
    colspan: int = Field(default=1, ge=1)
    rowspan: int = Field(default=1, ge=1)
    is_header: bool = False

    @property
    def area(self) -> int:
        """Grid positions this cell occupies."""
        return self.colspan * self.rowspan

    @property
    def spans(self) -> bool:
        return self.area > 1


class Block(BaseModel):
    """A node in the document tree.

    One recursive type rather than a class per kind, because the interesting operations
    (walk, count features, re-level) are uniform over kinds and a visitor over 8 classes
    would be more code saying the same thing.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "heading", "paragraph", "list", "list_item", "table", "row",
        "code", "quote", "image", "footnote",
    ]
    text: str = ""
    level: int | None = None
    """For headings: the level AS DECLARED BY THE SOURCE, 1-6. Never repaired in place --
    see outline.py for why a repair is a rewrite rather than a fix."""

    ordered: bool = False
    cells: tuple[Cell, ...] = ()
    children: tuple[Block, ...] = ()
    alt_text: str = ""
    """For images. An image containing text is the one feature where the CONTENT is
    unreachable without OCR, so it is tracked separately from IMAGE."""

    has_embedded_text: bool = False

    @model_validator(mode="after")
    def _check_shape(self) -> Block:
        if self.kind == "heading":
            if self.level is None:
                raise ValueError("a heading must carry the level its source declared")
            if not 1 <= self.level <= 6:
                raise ValueError(f"heading level {self.level} outside 1-6")
        elif self.level is not None:
            raise ValueError(f"{self.kind} carries a heading level")
        if self.cells and self.kind != "row":
            raise ValueError(f"{self.kind} carries cells; only a row may")
        return self

    def walk(self) -> list[Block]:
        """Depth-first, self first."""
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out

    def depth_of_kind(self, kind: str) -> int:
        """Deepest chain of nested `kind` at or below here.

        Used for nesting limits, which are where APPROXIMATE lives: a format may allow
        two levels of list and not four.
        """
        below = max((c.depth_of_kind(kind) for c in self.children), default=0)
        return below + 1 if self.kind == kind else below


class Document(BaseModel):
    """A parsed document, plus how confident we are that we read its bytes correctly."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    source_format: str
    blocks: tuple[Block, ...] = ()
    encoding_note: str = ""
    """Non-empty when the bytes were ambiguous. Carried on the document rather than
    raised, because a document that decoded oddly is still worth reading."""

    def walk(self) -> list[Block]:
        out: list[Block] = []
        for block in self.blocks:
            out.extend(block.walk())
        return out

    @property
    def text_content(self) -> str:
        """Every scrap of text, in order, with no structure at all.

        This exists to be compared against itself after a conversion. Two documents with
        identical `text_content` can have completely different trees, which is the whole
        problem with checking a conversion by diffing its text.
        """
        parts: list[str] = []
        for block in self.walk():
            if block.text:
                parts.append(block.text)
            for cell in block.cells:
                if cell.text:
                    parts.append(cell.text)
        return "\n".join(parts)

    @property
    def headings(self) -> tuple[Block, ...]:
        return tuple(b for b in self.walk() if b.kind == "heading")


class FeatureLoss(BaseModel):
    """One feature, in one document, and what the target format did to it."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    feature: Feature
    fidelity: Fidelity
    target: str
    count: int = Field(ge=1)
    detail: str = ""

    @property
    def is_loss(self) -> bool:
        return self.fidelity is not Fidelity.EXACT

    @property
    def changes_content(self) -> bool:
        """Whether the CONTENT moved, as opposed to the structure around it.

        DEGRADED keeps every character and loses a relationship. INVENTED and DROPPED
        change what the text says. A reviewer who only has time for one of these wants
        this one.
        """
        return self.fidelity in (Fidelity.INVENTED, Fidelity.DROPPED)
