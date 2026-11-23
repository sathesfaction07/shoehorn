"""Tables, and the arithmetic that makes a merged cell unrepresentable in a grid.

A table as authored is a list of rows of cells, where a cell may declare that it covers
several grid positions. A table as rendered by a pipe-delimited format is a GRID: every
row has the same number of cells, because the delimiter count fixes it.

The two are not the same shape, and the difference is countable:

    A grid of R rows and C columns has exactly R*C positions.
    A cell covering colspan*rowspan positions is ONE value.
    So a table containing a merged cell has FEWER cells than positions.

Which gives the result this module exists to state: converting such a table to a grid must
either write one value into several positions (INVENTED -- the output asserts columns that
were never separately labelled) or leave positions empty (DEGRADED -- the value survives
and the fact that it covered those columns does not). There is no third option.

The occupancy walk below handles `rowspan` properly rather than summing `colspan` per row,
because a cell spanning downward occupies a position in a row it does not appear in, and
any count that ignores that reports a rectangular table as ragged.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .models import Cell


class Shape(StrEnum):
    """Whether a grid exists for this table at all."""

    RECTANGULAR = "rectangular"
    """Every position in the bounding box is covered exactly once. A grid exists."""

    RAGGED = "ragged"
    """Positions are uncovered or covered twice. No grid exists, so ANY grid-based
    rendering must invent or discard content -- before the question of merged cells."""

    EMPTY = "empty"


class FlattenPolicy(StrEnum):
    """How to write a spanning cell into a grid. Both choices are wrong, differently."""

    DUPLICATE = "duplicate"
    """Write the value into every position it covers. The output then asserts that each
    column carried that value in its own right, which the source did not say."""

    BLANK = "blank"
    """Write the value once, leave the rest empty. Content survives; the span does not."""


class Occupancy(BaseModel):
    """The result of walking a table's cells onto a grid."""

    model_config = ConfigDict(frozen=True)

    rows: int
    cols: int
    cell_count: int
    covered_positions: int
    """Sum of every cell's area. Equals rows*cols exactly when a grid exists."""

    overlaps: int
    """Positions two cells both claim. Non-zero means the source table is malformed."""

    holes: int
    """Positions no cell claims."""

    @property
    def positions(self) -> int:
        return self.rows * self.cols

    @property
    def shape(self) -> Shape:
        if self.cell_count == 0:
            return Shape.EMPTY
        if self.overlaps or self.holes:
            return Shape.RAGGED
        return Shape.RECTANGULAR

    @property
    def merged_cells(self) -> int:
        """Positions that exist only because something spans.

        `positions - cell_count` for a rectangular table: each spanning cell contributes
        `area - 1` positions beyond its own. This is exactly the number of grid slots a
        pipe renderer has to fill with something the source never provided.
        """
        return self.positions - self.cell_count


def occupancy(rows: tuple[tuple[Cell, ...], ...]) -> Occupancy:
    """Walk cells onto a grid, honouring rowspan.

    A cell is placed at the first column of its row not already claimed by a cell spanning
    down from above. That is how a browser lays a table out, and it is the only placement
    that makes a rowspan-bearing table come out rectangular.
    """
    if not rows or all(len(r) == 0 for r in rows):
        return Occupancy(rows=0, cols=0, cell_count=0, covered_positions=0, overlaps=0, holes=0)

    claims: dict[tuple[int, int], int] = {}
    cell_count = 0
    covered = 0

    for r, row in enumerate(rows):
        col = 0
        for cell in row:
            cell_count += 1
            covered += cell.area
            while (r, col) in claims:
                col += 1
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    claims[(r + dr, col + dc)] = claims.get((r + dr, col + dc), 0) + 1
            col += cell.colspan

    max_r = max(r for r, _ in claims) + 1
    max_c = max(c for _, c in claims) + 1
    overlaps = sum(n - 1 for n in claims.values() if n > 1)
    holes = max_r * max_c - len(claims)

    return Occupancy(
        rows=max_r,
        cols=max_c,
        cell_count=cell_count,
        covered_positions=covered,
        overlaps=overlaps,
        holes=holes,
    )


class Flattened(BaseModel):
    """A table written into a grid, and what that cost.

    The three counters were not the three I first wrote. An earlier version carried
    `dropped_cells` for "a cell that did not fit", which is UNREACHABLE by construction --
    `occupancy` and `flatten` run the identical placement walk, so the bounding box the
    first computes always has room for every cell the second places. 0 hits over 30,000
    random tables. Meanwhile the case that DOES occur had no counter at all: 26,174 of
    those 30,000 had holes, which were quietly filled with empty strings.

    A field for an impossible failure made the model look more careful than it was, while
    the real one went unreported.
    """

    model_config = ConfigDict(frozen=True)

    grid: tuple[tuple[str, ...], ...]
    policy: FlattenPolicy
    duplicated_positions: int
    """Positions holding a value copied from a cell that did not own them. The output
    asserts a column carried that value in its own right; the source did not say so."""

    blanked_positions: int
    """Positions a span covered, left empty because the value went to the corner."""

    padded_positions: int
    """Holes in a RAGGED source, filled to make the rectangle close.

    A distinct kind of fabrication from a duplicated value: the output says "this cell was
    blank" where the source said "there is no cell here". Those are different claims, and
    a grid has no way to tell them apart.
    """

    @property
    def is_faithful(self) -> bool:
        return not (self.duplicated_positions or self.blanked_positions or self.padded_positions)


def flatten(
    rows: tuple[tuple[Cell, ...], ...],
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> Flattened:
    """Write a table into a rectangular grid under one of the two possible policies.

    Returns the grid AND the cost, because a caller that only receives the grid has no way
    to find out that a value in it was never in the source.
    """
    occ = occupancy(rows)
    if occ.cell_count == 0:
        return Flattened(
            grid=(), policy=policy, duplicated_positions=0, blanked_positions=0,
            padded_positions=0,
        )

    grid: list[list[str | None]] = [[None] * occ.cols for _ in range(occ.rows)]
    duplicated = 0
    blanked = 0

    for r, row in enumerate(rows):
        col = 0
        for cell in row:
            while col < occ.cols and grid[r][col] is not None:
                col += 1
            if col >= occ.cols:
                # Unreachable: occupancy sized the box from this same walk. Reaching it
                # means the two have diverged, which is a bug in this module rather than a
                # property of the table, so it must not be quietly counted as data loss.
                raise AssertionError(
                    f"placement disagrees with occupancy at row {r}: no column free "
                    f"below {occ.cols} for {cell.text!r}"
                )
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    rr, cc = r + dr, col + dc
                    if rr >= occ.rows or cc >= occ.cols:
                        continue
                    if dr == 0 and dc == 0:
                        grid[rr][cc] = cell.text
                    elif policy is FlattenPolicy.DUPLICATE:
                        grid[rr][cc] = cell.text
                        duplicated += 1
                    else:
                        grid[rr][cc] = ""
                        blanked += 1
            col += cell.colspan

    # Whatever is still None was never claimed by any cell. For a rectangular table there
    # is nothing here; for a ragged one this is the count that used to go unreported.
    padded = sum(1 for row in grid for v in row if v is None)

    return Flattened(
        grid=tuple(tuple("" if v is None else v for v in row) for row in grid),
        policy=policy,
        duplicated_positions=duplicated,
        blanked_positions=blanked,
        padded_positions=padded,
    )


def distinct_values(grid: tuple[tuple[str, ...], ...]) -> int:
    """Distinct non-empty strings in a grid.

    Used to show that DUPLICATE does not change this while it does change the number of
    CELLS holding each value -- so a check comparing the set of values before and after
    conversion sees nothing, which is why the count has to be reported separately.
    """
    return len({v for row in grid for v in row if v})
