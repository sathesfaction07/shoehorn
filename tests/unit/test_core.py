"""The arithmetic: the format ceiling, merged cells, and the outline collapse."""

from __future__ import annotations

import random
from math import comb

import pytest

from conftest import cell
from doc_consolidator.formats import (
    JSON,
    TARGETS,
    best_target,
    capability,
    ceiling,
    expressiveness,
    unverifiable_claims,
    verify_claims,
)
from doc_consolidator.models import Block, Expressiveness, Feature
from doc_consolidator.outline import (
    MAX_LEVEL,
    Reading,
    build_outline,
    collapse_census,
    depth_signature,
    find_skips,
    implied_nodes,
    max_depth,
)
from doc_consolidator.tables import (
    FlattenPolicy,
    Shape,
    distinct_values,
    flatten,
    occupancy,
)


def headings(*levels: int) -> tuple[Block, ...]:
    return tuple(
        Block(kind="heading", level=lv, text=f"h{lv}#{i}") for i, lv in enumerate(levels)
    )


class TestTheTargetFormatIsTheCeiling:
    """"Preserve structure" is not a parser property. It is a grammar property."""

    def test_markdown_cannot_hold_a_merged_cell_and_wiki_can(self):
        assert expressiveness("markdown", Feature.MERGED_CELL) is Expressiveness.ABSENT
        assert expressiveness("wiki", Feature.MERGED_CELL) is Expressiveness.NATIVE
        # And the ABSENT claim carries a reason derived from the delimiter structure.
        reason = capability("markdown", Feature.MERGED_CELL).reason
        assert "pipe row" in reason
        assert "arithmetic" in reason

    def test_the_pipe_row_arithmetic_holds(self):
        """A pipe row's cell count is fixed by its delimiters. That is the whole argument.

        The split is deliberate rather than a list literal: replacing it with the answer
        would assert my arithmetic instead of performing it, which is the entire point.
        """
        assert len([c for c in "| a | b |".split("|") if c.strip()]) == 2  # noqa: SIM905
        assert len([c for c in "| a | b | c |".split("|") if c.strip()]) == 3  # noqa: SIM905

    def test_every_limited_claim_carries_a_reason(self):
        assert verify_claims() == []
        for name, table in TARGETS.items():
            for feature, cap in table.items():
                if cap.expressiveness is not Expressiveness.NATIVE:
                    assert cap.reason, f"{name}/{feature.value} has no reason"

    def test_a_claim_of_limited_expressiveness_without_a_reason_is_rejected(self):
        from doc_consolidator.formats import Capability

        with pytest.raises(ValueError, match="must carry a reason"):
            Capability(Expressiveness.ABSENT, "")

    def test_implementation_claims_are_reported_separately_from_grammar_ones(self):
        """A claim that cannot be checked must not look like one that was."""
        weak = unverifiable_claims()
        assert weak, "expected some claims to rest on implementation behaviour"
        for name, feature, reason in weak:
            assert not capability(name, feature).from_grammar
            assert reason
        # The merged-cell claim is NOT among them -- it is arithmetic.
        assert ("markdown", Feature.MERGED_CELL) not in [
            (n, f) for n, f, _ in weak
        ]

    def test_json_is_the_lossless_control(self):
        """If json loses nothing and markdown loses a span, the loss is the format's."""
        lossy = [
            f.value
            for f, c in JSON.items()
            if c.expressiveness is not Expressiveness.NATIVE
        ]
        assert lossy == [Feature.IMAGE_TEXT.value]

    def test_no_target_claims_to_recover_text_from_pixels(self):
        """IMAGE_TEXT is a property of the SOURCE, so even the control cannot rescue it."""
        for name in TARGETS:
            assert expressiveness(name, Feature.IMAGE_TEXT) is not Expressiveness.NATIVE

    def test_the_ceiling_is_computable_before_any_conversion(self):
        counts = {Feature.HEADING: 3, Feature.TABLE: 1, Feature.MERGED_CELL: 2}
        assert ceiling("markdown", counts) == (4, 2)
        assert ceiling("wiki", counts) == (6, 0)
        assert best_target(counts) == ("json", 0)

    def test_plain_is_the_other_end_of_the_range(self):
        counts = {Feature.TABLE: 1, Feature.NESTED_LIST: 1}
        assert ceiling("plain", counts) == (0, 2)

    def test_an_unknown_target_raises_rather_than_defaulting(self):
        with pytest.raises(KeyError, match="unknown target"):
            capability("pdf", Feature.HEADING)


class TestAMergedCellHasNoGridRepresentation:
    """R*C positions, and a spanning cell is one value. The counts cannot both be right."""

    def test_the_invariant_holds_exactly_for_a_rectangular_table(self, colspan_table):
        occ = occupancy(colspan_table)
        assert (occ.rows, occ.cols) == (2, 2)
        assert occ.cell_count == 3
        assert occ.positions == 4
        assert occ.covered_positions == occ.positions
        assert occ.shape is Shape.RECTANGULAR
        assert occ.merged_cells == 1

    def test_rowspan_is_handled_and_a_colspan_only_count_would_not_be(
        self, rowspan_table
    ):
        occ = occupancy(rowspan_table)
        assert occ.shape is Shape.RECTANGULAR
        assert (occ.rows, occ.cols) == (2, 2)
        # The naive count: sum colspan per row gives 2 then 1, so the rows look unequal
        # and the table looks ragged. It is not.
        naive = [sum(c.colspan for c in row) for row in rowspan_table]
        assert naive == [2, 1]
        assert len(set(naive)) > 1, "the naive count disagrees with itself"

    def test_a_ragged_table_has_no_grid_at_all(self, ragged_table):
        occ = occupancy(ragged_table)
        assert occ.shape is Shape.RAGGED
        assert occ.holes == 2
        assert occ.covered_positions != occ.positions

    def test_both_repairs_are_wrong_and_they_fail_in_opposite_directions(
        self, colspan_table
    ):
        duplicated = flatten(colspan_table, FlattenPolicy.DUPLICATE)
        blanked = flatten(colspan_table, FlattenPolicy.BLANK)

        assert duplicated.grid == (("Q1", "Q1"), ("Jan", "Feb"))
        assert duplicated.duplicated_positions == 1
        assert duplicated.blanked_positions == 0

        assert blanked.grid == (("Q1", ""), ("Jan", "Feb"))
        assert blanked.duplicated_positions == 0
        assert blanked.blanked_positions == 1

        assert not duplicated.is_faithful
        assert not blanked.is_faithful

    def test_neither_repair_changes_the_value_set_so_a_content_check_passes(
        self, colspan_table
    ):
        """The reason the loss is silent, stated as arithmetic."""
        source_values = {c.text for row in colspan_table for c in row}
        for policy in FlattenPolicy:
            flat = flatten(colspan_table, policy)
            grid_values = {v for row in flat.grid for v in row if v}
            assert grid_values == source_values
            assert distinct_values(flat.grid) == len(source_values)

    def test_a_ragged_source_gains_positions_that_are_counted(self, ragged_table):
        """The counter that did not exist in the first version."""
        flat = flatten(ragged_table, FlattenPolicy.DUPLICATE)
        assert flat.padded_positions == 2
        assert not flat.is_faithful
        assert flat.grid == (("Summary", "", ""), ("a", "b", "c"))

    def test_a_rectangular_table_pads_nothing(self, colspan_table, rowspan_table):
        for rows in (colspan_table, rowspan_table):
            assert flatten(rows, FlattenPolicy.DUPLICATE).padded_positions == 0

    def test_a_faithful_table_reports_faithful(self):
        plain = ((cell("a"), cell("b")), (cell("c"), cell("d")))
        flat = flatten(plain, FlattenPolicy.DUPLICATE)
        assert flat.is_faithful
        assert occupancy(plain).merged_cells == 0

    def test_placement_never_runs_out_of_room(self):
        """`occupancy` and `flatten` share the placement walk, so the no-room branch is
        unreachable by construction. 0 hits over 30,000 random tables when this was
        probed; asserted here over a smaller sample so the suite stays fast."""
        rng = random.Random(11)
        for _ in range(2000):
            rows = tuple(
                tuple(
                    cell(f"{r}{i}", rng.randint(1, 3), rng.randint(1, 3))
                    for i in range(rng.randint(1, 3))
                )
                for r in range(rng.randint(1, 4))
            )
            flat = flatten(rows, FlattenPolicy.DUPLICATE)  # raises if they diverge
            occ = occupancy(rows)
            assert len(flat.grid) == occ.rows
            if occ.cols:
                assert all(len(row) == occ.cols for row in flat.grid)

    def test_an_empty_table_is_empty_not_rectangular(self):
        assert occupancy(()).shape is Shape.EMPTY
        assert occupancy(((),)).shape is Shape.EMPTY
        assert flatten(()).grid == ()

    def test_a_cell_cannot_declare_a_zero_span(self):
        with pytest.raises(ValueError):
            cell("x", colspan=0)
        with pytest.raises(ValueError):
            cell("x", rowspan=0)


class TestTheOutlineMapIsNotInjective:
    """Flat declared levels to a tree. Different documents, identical outlines."""

    def test_two_different_documents_produce_the_same_tree(self):
        skipped = depth_signature(build_outline(headings(1, 3), Reading.PROMOTE))
        clean = depth_signature(build_outline(headings(1, 2), Reading.PROMOTE))
        assert skipped == clean == (1, 2)

    def test_the_two_readings_disagree_on_the_same_source(self):
        promote = build_outline(headings(1, 3), Reading.PROMOTE)
        implicit = build_outline(headings(1, 3), Reading.IMPLICIT)
        assert max_depth(promote) == 2
        assert max_depth(implicit) == 3
        assert implied_nodes(promote) == 0
        assert implied_nodes(implicit) == 1
        assert depth_signature(promote) != depth_signature(implicit)

    def test_a_document_starting_deep_is_the_same_ambiguity(self):
        skips = find_skips(headings(3))
        assert len(skips) == 1
        assert (skips[0].from_level, skips[0].to_level, skips[0].gap) == (0, 3, 2)
        assert max_depth(build_outline(headings(3), Reading.PROMOTE)) == 1
        assert max_depth(build_outline(headings(3), Reading.IMPLICIT)) == 3

    def test_no_skip_means_the_readings_agree(self):
        for levels in ((1,), (1, 2), (1, 2, 3, 2, 1)):
            assert find_skips(headings(*levels)) == ()
            assert depth_signature(
                build_outline(headings(*levels), Reading.PROMOTE)
            ) == depth_signature(build_outline(headings(*levels), Reading.IMPLICIT))

    def test_declared_level_is_preserved_and_never_rewritten_in_place(self):
        source = headings(1, 3)
        forest = build_outline(source, Reading.PROMOTE)
        nodes = [n for root in forest for n in root.walk()]
        deep = next(n for n in nodes if n.text == source[1].text)
        assert deep.declared_level == 3
        assert deep.depth == 2
        assert source[1].level == 3, "the source block must be untouched"

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
    def test_promote_produces_exactly_catalan_n_distinct_outlines(self, n: int):
        """A promote-normalised outline IS an ordered forest on n nodes."""
        total, distinct = collapse_census(n, Reading.PROMOTE)
        assert total == MAX_LEVEL**n
        assert distinct == comb(2 * n, n) // (n + 1)

    def test_the_catalan_identity_breaks_by_exactly_one_past_six_levels(self):
        """At n=7 the missing forest is the single depth-7 chain, which 6 levels cannot
        express. Off by exactly one is what confirms the explanation."""
        total, distinct = collapse_census(7, Reading.PROMOTE)
        catalan = comb(14, 7) // 8
        assert catalan == 429
        assert distinct == 428
        assert catalan - distinct == 1
        assert total == MAX_LEVEL**7

    def test_the_collapse_grows_without_bound(self):
        ratios = []
        for n in range(1, 7):
            total, distinct = collapse_census(n, Reading.PROMOTE)
            ratios.append(total / distinct)
        assert ratios == sorted(ratios)
        assert ratios[0] == pytest.approx(6.0)
        assert ratios[-1] == pytest.approx(353.45, abs=0.1)

    def test_implicit_keeps_more_and_pays_for_it_with_invented_nodes(self):
        """At n=1 IMPLICIT is injective where PROMOTE maps all six levels to one tree."""
        _, promote = collapse_census(1, Reading.PROMOTE)
        _, implicit = collapse_census(1, Reading.IMPLICIT)
        assert promote == 1
        assert implicit == MAX_LEVEL
        assert implied_nodes(build_outline(headings(6), Reading.IMPLICIT)) == 5

    def test_two_roots_stay_two_roots(self):
        """Inventing a wrapper to force one tree would be a third silent decision."""
        forest = build_outline(headings(1, 1), Reading.PROMOTE)
        assert len(forest) == 2

    def test_a_heading_must_carry_its_declared_level(self):
        with pytest.raises(ValueError, match="must carry the level"):
            Block(kind="heading", text="x")

    def test_a_non_heading_must_not_carry_one(self):
        with pytest.raises(ValueError, match="carries a heading level"):
            Block(kind="paragraph", text="x", level=2)

    def test_a_level_outside_one_to_six_is_rejected(self):
        for bad in (0, 7):
            with pytest.raises(ValueError, match="outside 1-6"):
                Block(kind="heading", level=bad, text="x")

    def test_only_a_row_may_carry_cells(self):
        with pytest.raises(ValueError, match="only a row may"):
            Block(kind="paragraph", cells=(cell("x"),))

    def test_an_empty_heading_sequence_gives_an_empty_forest(self):
        assert build_outline((), Reading.PROMOTE) == ()
        assert max_depth(()) == 0
        assert depth_signature(()) == ()
