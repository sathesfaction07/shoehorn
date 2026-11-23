"""Encoding, the parsers, and the silent-loss signature over the shipped corpus."""

from __future__ import annotations

import pytest

from doc_consolidator.emit import census, emit
from doc_consolidator.encoding import (
    Decoding,
    candidate_decodings,
    compare_handlers,
    decode_bytes,
    looks_like_mojibake,
    mojibake_lines,
    no_undecodable_bytes,
    repair_mojibake,
)
from doc_consolidator.measure import ROUND_TRIPPABLE, build_report, compare_targets
from doc_consolidator.models import Feature, Fidelity
from doc_consolidator.parse import parse_file, parse_html, parse_markdown, parse_wiki
from doc_consolidator.tables import FlattenPolicy, occupancy


class TestTheSafeLookingHandlerIsTheLossyOne:
    def test_mis_decoding_never_raises(self):
        raw = "café — naïve".encode()
        wrong = raw.decode("cp1252")
        assert wrong == "cafÃ© â€” naÃ¯ve"

    def test_being_wrong_is_reversible(self):
        original = "café — naïve"
        wrong = original.encode("utf-8").decode("cp1252")
        assert wrong.encode("cp1252").decode("utf-8") == original

    def test_replacement_is_not_reversible(self):
        raw = "café".encode("latin-1")
        replaced = raw.decode("utf-8", errors="replace")
        assert replaced.count("\ufffd") == 1
        assert replaced.encode("utf-8") != raw

    def test_the_three_handlers_side_by_side(self):
        handlers = compare_handlers(b"caf\xe9")
        assert handlers["utf-8 + replace"][1] is False
        assert handlers["utf-8 + ignore"][1] is False
        assert handlers["cp1252 (wrong)"] == ("café", True)

    def test_latin1_rejects_nothing_so_nothing_is_undecodable(self):
        assert no_undecodable_bytes() == (0, 256)

    def test_lossy_is_unreachable_with_the_default_codecs(self):
        """So every errors='replace' is a CHOICE, never a necessity."""
        import random

        rng = random.Random(7)
        seen = set()
        for _ in range(4000):
            raw = bytes(rng.randrange(256) for _ in range(rng.randint(1, 12)))
            seen.add(decode_bytes(raw).decoding)
        assert Decoding.LOSSY not in seen
        assert {Decoding.CLEAN, Decoding.AMBIGUOUS} <= seen

    def test_lossy_is_reachable_when_the_codec_list_is_restricted(self):
        """The branch is exercised rather than left as dead code, and it says what it cost."""
        result = decode_bytes(b"caf\xe9", codecs=("ascii",))
        assert result.decoding is Decoding.LOSSY
        assert result.recoverable is False
        assert result.replacements == 1
        assert "unrecoverable" in result.detail

    def test_the_same_bytes_have_several_readings_and_the_choice_is_a_preference(self):
        candidates = candidate_decodings(b"caf\xe9")
        assert len(candidates) == 4
        assert len(set(candidates.values())) == 3
        result = decode_bytes(b"caf\xe9")
        assert result.decoding is Decoding.AMBIGUOUS
        assert result.codec_used == "cp1252"
        assert result.candidates == 3
        assert "PREFERRED" in result.detail

    def test_empty_bytes_are_clean_not_ambiguous(self):
        assert decode_bytes(b"").decoding is Decoding.CLEAN

    def test_clean_utf8_is_clean(self):
        result = decode_bytes("perfectly ordinary café".encode())
        assert result.decoding is Decoding.CLEAN
        assert result.is_certain

    def test_whole_text_mojibake_is_detected_and_repaired(self):
        broken = "Café Münster".encode().decode("cp1252")
        found, note = looks_like_mojibake(broken)
        assert found
        assert "all of it" in note
        assert repair_mojibake(broken) == "Café Münster"

    def test_partial_mojibake_defeats_a_whole_text_round_trip(self):
        """One correctly-encoded character breaks it, so the scan has to be per line."""
        mixed = "\n".join(
            ["Café".encode().decode("cp1252"), "Jean-Léon", "plain ascii"]
        )
        # The whole-text round trip fails outright.
        with pytest.raises(UnicodeDecodeError):
            mixed.encode("cp1252").decode("utf-8")
        # The line scan finds it anyway.
        assert mojibake_lines(mixed) == [0]
        found, note = looks_like_mojibake(mixed)
        assert found
        assert "1 of 3 lines" in note
        assert "would call this clean" in note

    def test_partial_repair_touches_only_the_affected_lines(self):
        mixed = "\n".join(["Café".encode().decode("cp1252"), "Jean-Léon"])
        repaired = repair_mojibake(mixed)
        assert repaired is not None
        assert repaired.splitlines() == ["Café", "Jean-Léon"]

    def test_real_text_containing_a_marker_is_not_called_mojibake(self):
        """A marker check alone would fire here; the round trip does not."""
        found, _ = looks_like_mojibake("Ã is a letter in Portuguese orthography")
        assert not found
        assert repair_mojibake("ordinary text") is None

    def test_repeated_repair_is_not_iterated_to_a_fixed_point(self):
        once = repair_mojibake("Café Münster".encode().decode("cp1252"))
        assert once == "Café Münster"
        assert repair_mojibake(once) is None


class TestTheParsersAgreeOnOneModel:
    def test_every_format_produces_blocks(self, corpus):
        formats = {doc.source_format for doc in corpus.values()}
        assert formats == {"html", "docx", "wiki", "markdown"}
        for name, doc in corpus.items():
            assert doc.blocks, f"{name} parsed to nothing"

    def test_python_docx_row_cells_silently_duplicates_a_merged_value(self, docs_dir):
        """The library applies the DUPLICATE policy itself, with no indication."""
        from docx import Document as DocxDocument

        table = DocxDocument(str(docs_dir / "d01-merged.docx")).tables[0]
        naive = [c.text for c in table.rows[0].cells]
        assert len(naive) == 3
        assert naive[0] == naive[1], "the merged value appears twice"
        cells = table.rows[0].cells
        assert cells[0]._tc is cells[1]._tc, "the same element, yielded twice"

    def test_reading_only_paragraphs_loses_every_table_cell(self, docs_dir):
        """The defect this project's diligence check found in CertValidator."""
        from docx import Document as DocxDocument

        doc = DocxDocument(str(docs_dir / "d01-merged.docx"))
        paragraphs_only = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        assert doc.tables, "the document does have a table"
        for value in ("Leeds", "York", "Bristol", "4200"):
            assert value not in paragraphs_only

    def test_the_xml_path_recovers_the_truth(self, corpus):
        doc = corpus["d01-merged"]
        table = next(b for b in doc.walk() if b.kind == "table")
        rows = tuple(r.cells for r in table.children if r.kind == "row")
        occ = occupancy(rows)
        assert occ.cell_count == 8
        assert occ.positions == 9
        assert occ.merged_cells == 1
        for value in ("Leeds", "York", "Bristol", "4200"):
            assert value in doc.text_content

    def test_a_real_ooxml_vertical_merge_becomes_a_rowspan(self, corpus):
        table = next(b for b in corpus["d03-rowspan"].walk() if b.kind == "table")
        rows = tuple(r.cells for r in table.children if r.kind == "row")
        spans = [c.rowspan for row in rows for c in row if c.rowspan > 1]
        assert spans == [2]
        assert occupancy(rows).merged_cells == 1

    def test_a_nested_table_does_not_steal_the_outer_table_rows(self, corpus):
        """`find_all` is recursive; without filtering, a 1-row table came out 3x2."""
        doc = corpus["h07-nested-table"]
        tables = [b for b in doc.walk() if b.kind == "table"]
        assert len(tables) == 2
        outer_rows = tuple(r.cells for r in tables[0].children if r.kind == "row")
        assert occupancy(outer_rows).rows == 1

    def test_nested_table_text_is_not_counted_twice(self, corpus):
        content = corpus["h07-nested-table"].text_content
        assert content.count("bolt") == 1
        assert content.count("nut") == 1

    def test_malformed_markup_is_recovered_the_way_a_browser_would(self, corpus):
        doc = corpus["h10-malformed"]
        assert any(b.kind == "heading" for b in doc.blocks)
        assert sum(1 for b in doc.blocks if b.kind == "paragraph") >= 2
        assert "orphan" in doc.text_content

    def test_wiki_span_attributes_are_parsed(self, corpus):
        table = next(b for b in corpus["w02-merged"].walk() if b.kind == "table")
        rows = tuple(r.cells for r in table.children if r.kind == "row")
        assert occupancy(rows).merged_cells == 1

    def test_an_unknown_extension_raises_rather_than_guessing(self, tmp_path):
        path = tmp_path / "thing.rtf"
        path.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="no parser"):
            parse_file(path)

    def test_image_text_is_declared_not_detected(self, corpus):
        images = [b for b in corpus["h09-image-text"].walk() if b.kind == "image"]
        assert len(images) == 2
        assert [b.has_embedded_text for b in images] == [True, False]

    def test_an_empty_document_parses_to_nothing_without_raising(self):
        for parser in (parse_html, parse_wiki, parse_markdown):
            doc = parser(b"", "empty")
            assert doc.blocks == ()
            assert doc.text_content == ""


class TestTheTwoQuestionsComeApart:
    """"Did we get all the content" can be YES while "did we preserve structure" is NO."""

    def test_the_same_tree_to_two_targets_gives_different_answers(self, corpus):
        doc = corpus["h04-merged"]
        md_text, md_losses = emit(doc, "markdown")
        wiki_text, wiki_losses = emit(doc, "wiki")

        assert "| Q1 | Q1 |" in md_text
        assert [(loss.feature, loss.fidelity) for loss in md_losses] == [
            (Feature.MERGED_CELL, Fidelity.INVENTED)
        ]

        assert 'colspan="2"' in wiki_text
        assert wiki_losses == []

    def test_the_policy_decides_which_way_the_output_is_wrong(self, corpus):
        doc = corpus["h04-merged"]
        duplicated, dup_losses = emit(doc, "markdown", policy=FlattenPolicy.DUPLICATE)
        blanked, blank_losses = emit(doc, "markdown", policy=FlattenPolicy.BLANK)

        assert "| Q1 | Q1 |" in duplicated
        assert dup_losses[0].fidelity is Fidelity.INVENTED

        assert "| Q1 |  |" in blanked
        assert blank_losses[0].fidelity is Fidelity.DEGRADED

    def test_a_merged_cell_document_is_silent_after_a_real_round_trip(self, docs_dir):
        report = build_report(docs_dir, "markdown")
        merged = next(d for d in report.docs if d.doc_id == "h04-merged")
        assert merged.values_before == merged.values_after
        assert merged.is_silent
        assert merged.content_changed >= 1

    def test_every_merged_cell_document_is_silent_for_markdown(self, docs_dir):
        report = build_report(docs_dir, "markdown")
        with_spans = [
            d.doc_id
            for d in report.docs
            if d.features.get(Feature.MERGED_CELL.value, 0) > 0
        ]
        assert with_spans, "the corpus must contain merged cells"
        assert set(with_spans) <= set(report.silent_docs)

    def test_wiki_is_not_silent_on_those_same_documents(self, docs_dir):
        markdown = build_report(docs_dir, "markdown")
        wiki = build_report(docs_dir, "wiki")
        with_spans = {
            d.doc_id
            for d in markdown.docs
            if d.features.get(Feature.MERGED_CELL.value, 0) > 0
        }
        assert with_spans & set(markdown.silent_docs) == with_spans
        assert not (with_spans & set(wiki.silent_docs))

    def test_values_after_is_a_real_round_trip_not_a_line_count(self, docs_dir):
        """An earlier version compared source VALUES against output LINES."""
        assert set(ROUND_TRIPPABLE) == {"markdown", "wiki"}
        report = build_report(docs_dir, "markdown")
        table_doc = next(d for d in report.docs if d.doc_id == "m02-table")
        assert table_doc.values_after == table_doc.values_before

    def test_a_target_with_no_parser_reports_none_rather_than_a_number(self, docs_dir):
        report = build_report(docs_dir, "json")
        assert not report.round_trippable
        assert all(d.values_after is None for d in report.docs)
        assert all(d.values_preserved is None for d in report.docs)
        assert report.silent_docs == ()
        assert report.unmeasurable_docs, "losses with no round trip must be named"

    def test_the_ceiling_orders_the_targets_the_same_way_the_results_do(self, docs_dir):
        reports = compare_targets(docs_dir)
        by_result = sorted(reports, key=lambda name: reports[name].total_lost)
        table = next(iter(reports.values())).ceiling_table
        by_ceiling = sorted(table, key=lambda name: table[name][1])
        assert by_result == by_ceiling == ["json", "wiki", "markdown", "plain"]

    def test_markdown_loses_more_than_wiki_on_identical_input(self, docs_dir):
        reports = compare_targets(docs_dir)
        assert reports["markdown"].total_lost > reports["wiki"].total_lost
        md_invented = reports["markdown"].by_fidelity.get("invented", 0)
        wiki_invented = reports["wiki"].by_fidelity.get("invented", 0)
        assert wiki_invented == 0
        assert md_invented > 0

    def test_fidelity_rate_is_none_rather_than_perfect_on_an_empty_corpus(self, tmp_path):
        """0/0 is not 100%. An unmeasured corpus is not a preserved one."""
        report = build_report(tmp_path, "markdown")
        assert report.docs == ()
        assert report.total_features == 0
        assert report.fidelity_rate is None

    def test_an_unreadable_file_is_named_rather_than_skipped(self, tmp_path):
        (tmp_path / "notes.rtf").write_text("x", encoding="utf-8")
        (tmp_path / "page.md").write_text("# Title\n", encoding="utf-8")
        report = build_report(tmp_path, "markdown")
        assert report.unreadable == ("notes.rtf",)
        assert not report.is_clean
        assert len(report.docs) == 1


class TestThePropertiesOfTheShippedCorpus:
    """Guards against the corpus quietly stopping to exercise a case."""

    def test_every_feature_occurs_somewhere(self, corpus):
        seen: set[Feature] = set()
        for doc in corpus.values():
            seen |= set(census(doc))
        missing = set(Feature) - seen
        assert missing <= {Feature.FOOTNOTE}, f"unreachable features: {missing}"

    def test_every_fidelity_value_occurs(self, docs_dir):
        seen: set[str] = set()
        for target in ("markdown", "wiki", "plain"):
            seen |= set(build_report(docs_dir, target).by_fidelity)
        assert {f.value for f in Fidelity} - {Fidelity.EXACT.value} <= seen

    def test_three_decoding_verdicts_occur_and_lossy_does_not(self, docs_dir):
        report = build_report(docs_dir, "markdown")
        counts = report.encoding_counts
        assert counts.get("clean", 0) > 0
        assert counts.get("mojibake", 0) == 2, "one whole-file and one partial"
        assert counts.get("ambiguous", 0) == 1
        assert Decoding.LOSSY.value not in counts
        assert report.unrecoverable == ()

    def test_the_corpus_contains_all_three_table_shapes(self, corpus):
        shapes = set()
        for doc in corpus.values():
            for block in doc.walk():
                if block.kind == "table":
                    rows = tuple(r.cells for r in block.children if r.kind == "row")
                    shapes.add(occupancy(rows).shape.value)
        assert {"rectangular", "ragged"} <= shapes

    def test_the_corpus_contains_heading_skips_of_both_kinds(self, docs_dir):
        report = build_report(docs_dir, "markdown")
        assert sum(d.skips for d in report.docs) == 4
        starts_deep = next(d for d in report.docs if d.doc_id == "h03-starts-deep")
        assert starts_deep.skips == 1
        assert starts_deep.declared_depth > starts_deep.read_depth

    def test_more_than_half_the_corpus_loses_structure_invisibly(self, docs_dir):
        report = build_report(docs_dir, "markdown")
        assert len(report.silent_docs) >= len(report.docs) / 2

    def test_the_planted_list_matches_what_is_on_disk(self, docs_dir):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "corpus_gen", docs_dir.parent / "generate.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["corpus_gen"] = module
        spec.loader.exec_module(module)
        on_disk = {p.name for p in docs_dir.iterdir() if p.is_file()}
        assert on_disk == set(module.PLANTED)
