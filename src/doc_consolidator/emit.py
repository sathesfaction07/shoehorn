"""Render a document to each target, and report what the target could not hold.

Every emitter returns `(text, losses)`. Returning only the text would make the loss
undiscoverable, which is the failure this project is about: a converter that hands back a
clean-looking markdown file has told you nothing about the merged cell it flattened.

The emitters share the same input tree, so any difference between their outputs is a
property of the target. That is the control.
"""

from __future__ import annotations

import json as jsonlib

from .models import Block, Document, Feature, FeatureLoss, Fidelity
from .outline import Reading, build_outline
from .tables import FlattenPolicy, flatten, occupancy


def _rows_of(table: Block) -> tuple[tuple, ...]:
    return tuple(r.cells for r in table.children if r.kind == "row")


def _nested_tables(table: Block) -> list[Block]:
    return [
        child
        for row in table.children
        for child in row.children
        if child.kind == "table"
    ]


def census(doc: Document) -> dict[Feature, int]:
    """Count the structural features present. The input to `ceiling`.

    Counted in GRID POSITIONS for merged cells rather than in cells, because the position is
    what a target has to find something to put in.
    """
    counts: dict[Feature, int] = {}

    def bump(feature: Feature, n: int = 1) -> None:
        if n:
            counts[feature] = counts.get(feature, 0) + n

    for block in doc.walk():
        if block.kind == "heading":
            bump(Feature.HEADING)
        elif block.kind == "paragraph":
            bump(Feature.PARAGRAPH)
        elif block.kind == "code":
            bump(Feature.CODE_BLOCK)
        elif block.kind == "quote":
            bump(Feature.BLOCKQUOTE)
        elif block.kind == "image":
            bump(Feature.IMAGE)
            if block.has_embedded_text:
                bump(Feature.IMAGE_TEXT)
        elif block.kind == "footnote":
            bump(Feature.FOOTNOTE)
        elif block.kind == "list":
            bump(Feature.LIST)
            if block.depth_of_kind("list") > 1:
                bump(Feature.NESTED_LIST)
            if any(
                grand.kind == "table"
                for item in block.children
                for grand in item.children
            ):
                bump(Feature.TABLE_IN_LIST)
        elif block.kind == "table":
            bump(Feature.TABLE)
            bump(Feature.MERGED_CELL, occupancy(_rows_of(block)).merged_cells)
            bump(Feature.NESTED_TABLE, len(_nested_tables(block)))

    return counts


# --------------------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------------------

def to_markdown(
    doc: Document,
    reading: Reading = Reading.PROMOTE,
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> tuple[str, list[FeatureLoss]]:
    """Emit GFM-flavoured markdown, and every structural claim it could not carry."""
    out: list[str] = []
    losses: list[FeatureLoss] = []

    def note(feature: Feature, fidelity: Fidelity, count: int, detail: str) -> None:
        losses.append(
            FeatureLoss(
                doc_id=doc.doc_id, feature=feature, fidelity=fidelity,
                target="markdown", count=count, detail=detail,
            )
        )

    def render_list(block: Block, indent: int = 0) -> None:
        marker = "1." if block.ordered else "-"
        for item in block.children:
            out.append(f"{'  ' * indent}{marker} {item.text}".rstrip())
            for child in item.children:
                if child.kind == "list":
                    render_list(child, indent + 1)
                elif child.kind == "table":
                    # A pipe table indented into a list item is not portable, so it is
                    # emitted at the outer level and the containment is reported lost.
                    note(
                        Feature.TABLE_IN_LIST, Fidelity.DEGRADED, 1,
                        "table moved out of the list item; the containment is not portable",
                    )
                    out.append("")
                    render_table(child)

    def render_table(block: Block) -> None:
        rows = _rows_of(block)
        occ = occupancy(rows)
        flat = flatten(rows, policy)

        if occ.merged_cells:
            fidelity = (
                Fidelity.INVENTED if policy is FlattenPolicy.DUPLICATE else Fidelity.DEGRADED
            )
            detail = (
                f"{occ.cell_count} cells over {occ.positions} grid positions; "
                + (
                    f"{flat.duplicated_positions} positions hold a copied value"
                    if policy is FlattenPolicy.DUPLICATE
                    else f"{flat.blanked_positions} positions left empty, span lost"
                )
            )
            note(Feature.MERGED_CELL, fidelity, occ.merged_cells, detail)

        if flat.padded_positions:
            note(
                Feature.TABLE, Fidelity.INVENTED, flat.padded_positions,
                f"source is {occ.shape.value}: {flat.padded_positions} positions had no "
                "cell at all and were filled to close the rectangle",
            )

        for _ in _nested_tables(block):
            note(
                Feature.NESTED_TABLE, Fidelity.DEGRADED, 1,
                "a pipe row ends at a newline, so the inner table is emitted after the "
                "outer one and the containment is lost",
            )

        if not flat.grid:
            return
        for index, row in enumerate(flat.grid):
            out.append("| " + " | ".join(row) + " |")
            if index == 0:
                out.append("| " + " | ".join("---" for _ in row) + " |")
        for nested in _nested_tables(block):
            out.append("")
            render_table(nested)

    # Headings are emitted at their READ depth, not their declared level, and the
    # difference is reported. Emitting the declared level would preserve the bytes and
    # produce a document whose outline contradicts its own numbering.
    forest = build_outline(doc.headings, reading)
    depth_by_text: dict[str, int] = {}
    for root in forest:
        for node in root.walk():
            if not node.is_implied:
                depth_by_text.setdefault(node.text, node.depth)

    for block in doc.blocks:
        if block.kind == "heading":
            depth = depth_by_text.get(block.text, block.level or 1)
            if block.level is not None and depth != block.level:
                note(
                    Feature.HEADING, Fidelity.DEGRADED, 1,
                    f"declared level {block.level} emitted at depth {depth} under the "
                    f"{reading.value} reading",
                )
            out.append(f"{'#' * min(depth, 6)} {block.text}")
        elif block.kind == "paragraph":
            out.append(block.text)
        elif block.kind == "list":
            render_list(block)
        elif block.kind == "table":
            render_table(block)
        elif block.kind == "code":
            out.extend(["```", block.text, "```"])
        elif block.kind == "quote":
            out.append(f"> {block.text}")
        elif block.kind == "image":
            out.append(f"![{block.alt_text}]({block.text})")
            if block.has_embedded_text:
                note(
                    Feature.IMAGE_TEXT, Fidelity.DROPPED, 1,
                    "the image is declared to contain text; no target can carry content "
                    "the source never provided as text, and this tool does not OCR",
                )
        out.append("")

    return "\n".join(out).rstrip() + "\n", losses


# --------------------------------------------------------------------------------------
# wiki
# --------------------------------------------------------------------------------------

def to_wiki(
    doc: Document, reading: Reading = Reading.PROMOTE
) -> tuple[str, list[FeatureLoss]]:
    """Emit MediaWiki markup, which CAN express a merged cell.

    The same tree that loses a span to markdown keeps it here. That is the finding, stated
    as two code paths rather than as an assertion.
    """
    out: list[str] = []
    losses: list[FeatureLoss] = []

    def note(feature: Feature, fidelity: Fidelity, count: int, detail: str) -> None:
        losses.append(
            FeatureLoss(
                doc_id=doc.doc_id, feature=feature, fidelity=fidelity,
                target="wiki", count=count, detail=detail,
            )
        )

    def render_list(block: Block, depth: int = 1) -> None:
        marker = ("#" if block.ordered else "*") * depth
        for item in block.children:
            out.append(f"{marker} {item.text}".rstrip())
            for child in item.children:
                if child.kind == "list":
                    render_list(child, depth + 1)
                elif child.kind == "table":
                    note(
                        Feature.TABLE_IN_LIST, Fidelity.DEGRADED, 1,
                        "wiki markup expresses a table inside a list item inconsistently; "
                        "emitted after the list",
                    )
                    render_table(child)

    def render_table(block: Block) -> None:
        out.append("{|")
        for row in (r for r in block.children if r.kind == "row"):
            parts: list[str] = []
            for cell in row.cells:
                attrs = []
                if cell.colspan > 1:
                    attrs.append(f'colspan="{cell.colspan}"')
                if cell.rowspan > 1:
                    attrs.append(f'rowspan="{cell.rowspan}"')
                prefix = f"{' '.join(attrs)} | " if attrs else ""
                parts.append(f"{prefix}{cell.text}")
            lead = "!" if row.cells and row.cells[0].is_header else "|"
            joiner = " !! " if lead == "!" else " || "
            out.append(f"{lead} {joiner.join(parts)}")
            out.append("|-")
            for nested in row.children:
                if nested.kind == "table":
                    render_table(nested)
        if out[-1] == "|-":
            out.pop()
        out.append("|}")

    forest = build_outline(doc.headings, reading)
    depth_by_text: dict[str, int] = {}
    for root in forest:
        for node in root.walk():
            if not node.is_implied:
                depth_by_text.setdefault(node.text, node.depth)

    for block in doc.blocks:
        if block.kind == "heading":
            depth = depth_by_text.get(block.text, block.level or 1)
            if block.level is not None and depth != block.level:
                note(
                    Feature.HEADING, Fidelity.DEGRADED, 1,
                    f"declared level {block.level} emitted at depth {depth} under the "
                    f"{reading.value} reading",
                )
            marks = "=" * min(depth, 6)
            out.append(f"{marks} {block.text} {marks}")
        elif block.kind == "paragraph":
            out.append(block.text)
        elif block.kind == "list":
            render_list(block)
        elif block.kind == "table":
            render_table(block)
        elif block.kind == "code":
            out.append("<pre>")
            out.append(block.text)
            out.append("</pre>")
        elif block.kind == "quote":
            out.append(f"<blockquote>{block.text}</blockquote>")
        elif block.kind == "image":
            out.append(f"[[File:{block.text}|alt={block.alt_text}]]")
            if block.has_embedded_text:
                note(
                    Feature.IMAGE_TEXT, Fidelity.DROPPED, 1,
                    "declared to contain text, which is unreachable without OCR",
                )
        out.append("")

    return "\n".join(out).rstrip() + "\n", losses


# --------------------------------------------------------------------------------------
# json and plain
# --------------------------------------------------------------------------------------

def to_json(doc: Document) -> tuple[str, list[FeatureLoss]]:
    """Serialise the model. Lossless except for text locked inside an image.

    This is the control, and it is also the honest recommendation. A tool that steered a
    reader towards a prettier format while knowing it drops content would be choosing
    presentation on their behalf.
    """
    losses = [
        FeatureLoss(
            doc_id=doc.doc_id, feature=Feature.IMAGE_TEXT, fidelity=Fidelity.DROPPED,
            target="json", count=1,
            detail="a property of the SOURCE, not of this target: the content is pixels",
        )
        for block in doc.walk()
        if block.kind == "image" and block.has_embedded_text
    ]
    return jsonlib.dumps(doc.model_dump(mode="json"), indent=2) + "\n", losses


def to_plain(doc: Document) -> tuple[str, list[FeatureLoss]]:
    """Text only. Included so the far end of the range is visible."""
    out: list[str] = []
    losses: list[FeatureLoss] = []
    counts = census(doc)

    for feature, count in counts.items():
        if feature in (Feature.PARAGRAPH,):
            continue
        fidelity = (
            Fidelity.DEGRADED
            if feature in (Feature.HEADING, Feature.LIST)
            else Fidelity.DROPPED
        )
        losses.append(
            FeatureLoss(
                doc_id=doc.doc_id, feature=feature, fidelity=fidelity, target="plain",
                count=count, detail="plain text has no block structure",
            )
        )

    for block in doc.walk():
        if block.text:
            out.append(block.text)
        for cell in block.cells:
            if cell.text:
                out.append(cell.text)
    return "\n".join(out) + "\n", losses


EMITTERS = {
    "markdown": to_markdown,
    "wiki": to_wiki,
    "json": to_json,
    "plain": to_plain,
}


def emit(
    doc: Document,
    target: str,
    reading: Reading = Reading.PROMOTE,
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> tuple[str, list[FeatureLoss]]:
    if target == "markdown":
        return to_markdown(doc, reading, policy)
    if target == "wiki":
        return to_wiki(doc, reading)
    if target == "json":
        return to_json(doc)
    if target == "plain":
        return to_plain(doc)
    raise KeyError(f"unknown target {target!r}; known: {sorted(EMITTERS)}")
