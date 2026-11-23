"""Every command, every exit-code reason, and the contents of the JSON report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doc_consolidator.cli import cli

DOCS = Path(__file__).resolve().parents[2] / "data" / "docs"


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("DC_DOCS", str(DOCS))
    runner = CliRunner()

    def invoke(*args: str):
        result = runner.invoke(cli, list(args), catch_exceptions=False)
        return result

    return invoke


class TestDoctor:
    def test_reports_config_parsers_and_the_matrix_state(self, run):
        result = run("doctor")
        assert result.exit_code == 0
        assert "declared metadata not sniffed" in result.output
        assert ".docx    -> docx" in result.output
        assert "every claim carries a reason" in result.output

    def test_separates_implementation_claims_from_grammar_ones(self, run):
        result = run("doctor")
        assert "rest on IMPLEMENTATION behaviour rather than grammar" in result.output
        assert "table_in_list" in result.output

    def test_states_the_encoding_consequence(self, run):
        result = run("doctor")
        assert "latin-1 rejects 0 of 256 byte values" in result.output
        assert "every errors='replace' is a CHOICE" in result.output

    def test_names_the_two_values_a_bool_collapses(self, run):
        result = run("doctor")
        assert "INVENTED and DROPPED are the two a `lossy: bool` collapses" in result.output


class TestMatrix:
    def test_shows_the_row_that_matters(self, run):
        result = run("matrix")
        assert result.exit_code == 0
        lines = [
            ln for ln in result.output.splitlines()
            if ln.startswith("  merged_cell")
        ]
        assert len(lines) == 1
        row = lines[0]
        # json yes, markdown NO, plain NO, wiki yes -- columns are sorted by name.
        assert row.split()[1:] == ["yes", "NO", "NO", "yes"]

    def test_explains_the_claim_arithmetically(self, run):
        result = run("matrix")
        assert "A pipe row holds" in result.output
        assert "Arithmetic, from the delimiters" in result.output

    def test_does_not_claim_to_ocr(self, run):
        result = run("matrix")
        assert "this tool does not OCR" in result.output


class TestReport:
    def test_reports_the_silent_signature(self, run):
        result = run("report")
        assert result.exit_code == 0
        assert "SILENT:" in result.output
        assert "set of text values stayed identical" in result.output
        assert "cannot see the second question's failure" in result.output

    def test_names_the_merged_cell_documents_as_silent(self, run):
        result = run("report")
        silent_block = result.output.split("SILENT:")[1]
        for doc_id in ("h04-merged", "d01-merged", "w02-merged", "h05-rowspan"):
            assert doc_id in silent_block

    def test_wiki_loses_less_and_hides_less(self, run):
        markdown = run("report", "--target", "markdown").output
        wiki = run("report", "--target", "wiki").output
        assert "invented" in markdown
        assert "invented" not in wiki.split("what was lost")[1].split("SILENT")[0]

    def test_an_unknown_target_is_refused(self, run):
        result = run("report", "--target", "pdf")
        assert result.exit_code != 0
        assert "unknown target" in result.output

    def test_json_output_carries_the_findings(self, run, tmp_path):
        result = run("report", "-o", str(tmp_path))
        assert result.exit_code == 0
        payload = json.loads((tmp_path / "report.json").read_text())

        assert payload["target"] == "markdown"
        assert payload["documents"] == 23
        assert payload["total_features"] == 98
        assert payload["total_lost"] == 18
        assert payload["fidelity_rate"] == pytest.approx(0.8163, abs=1e-3)
        assert payload["by_fidelity"]["invented"] == 9
        assert len(payload["silent_docs"]) == 13
        assert payload["unrecoverable"] == []
        assert payload["encoding_counts"]["mojibake"] == 2
        assert payload["encoding_counts"]["ambiguous"] == 1

        ceiling = payload["ceiling"]
        assert ceiling["json"][1] < ceiling["wiki"][1] < ceiling["markdown"][1]
        assert ceiling["markdown"][1] < ceiling["plain"][1]

        merged = next(d for d in payload["docs"] if d["doc_id"] == "h04-merged")
        assert merged["is_silent"] is True
        assert merged["values_before"] == merged["values_after"]
        assert merged["losses"][0]["feature"] == "merged_cell"
        assert merged["losses"][0]["fidelity"] == "invented"

    def test_json_reports_null_rather_than_a_number_when_no_round_trip_exists(
        self, run, tmp_path
    ):
        run("report", "--target", "json", "-o", str(tmp_path))
        payload = json.loads((tmp_path / "report.json").read_text())
        assert all(d["values_after"] is None for d in payload["docs"])
        assert payload["silent_docs"] == []

    def test_exits_one_when_a_file_cannot_be_read(self, monkeypatch, tmp_path):
        (tmp_path / "legacy.rtf").write_text("x", encoding="utf-8")
        (tmp_path / "page.md").write_text("# Title\n", encoding="utf-8")
        monkeypatch.setenv("DC_DOCS", str(tmp_path))
        result = CliRunner().invoke(cli, ["report"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "unreadable (1): legacy.rtf" in result.output


class TestCompare:
    def test_states_the_control(self, run):
        result = run("compare")
        assert result.exit_code == 0
        assert "only the target differs" in result.output
        assert "belongs to the FORMAT, not to the reader" in result.output

    def test_orders_targets_by_loss(self, run):
        result = run("compare")
        body = result.output.split("by fidelity")[1]
        order = [
            line.split()[0]
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("-")
        ][:4]
        assert order == ["json", "wiki", "markdown", "plain"]

    def test_does_not_hide_that_json_wins(self, run):
        result = run("compare")
        assert "fewest losses: json" in result.output
        assert "choosing presentation on their behalf" in result.output

    def test_quantifies_the_markdown_wiki_gap(self, run):
        result = run("compare")
        assert "markdown loses 18 where wiki loses 8" in result.output


class TestCheck:
    def test_passes_on_the_shipped_corpus(self, run):
        result = run("check")
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_reports_the_world_without_failing_on_it(self, run):
        result = run("check")
        assert "Reported and NOT failed on" in result.output
        assert "heading skips:              4" in result.output
        assert "merged-cell grid positions: 7" in result.output
        assert "switched off inside a week" in result.output

    def test_fails_on_a_file_no_parser_claims(self, monkeypatch, tmp_path):
        (tmp_path / "scan.tiff").write_bytes(b"\x00\x01")
        monkeypatch.setenv("DC_DOCS", str(tmp_path))
        result = CliRunner().invoke(cli, ["check"], catch_exceptions=False)
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "no parser for 1" in result.output

    def test_a_merged_cell_alone_does_not_fail_the_gate(self, monkeypatch, tmp_path):
        (tmp_path / "spanning.html").write_text(
            "<h1>T</h1><table><tr><th colspan='2'>Q1</th></tr>"
            "<tr><td>a</td><td>b</td></tr></table>",
            encoding="utf-8",
        )
        monkeypatch.setenv("DC_DOCS", str(tmp_path))
        result = CliRunner().invoke(cli, ["check"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "PASS" in result.output
        assert "merged-cell grid positions: 1" in result.output


class TestOutline:
    def test_shows_both_readings_disagreeing(self, run):
        result = run("outline", "h02-skip")
        assert result.exit_code == 0
        assert "promote" in result.output
        assert "implicit" in result.output
        assert "level 1 -> 3" in result.output
        assert "Neither is a fix" in result.output

    def test_a_clean_document_says_the_readings_agree(self, run):
        result = run("outline", "h01-clean")
        assert "no skips, so both readings agree" in result.output

    def test_a_document_starting_deep_is_flagged(self, run):
        result = run("outline", "h03-starts-deep")
        assert "level 0 -> 3" in result.output

    def test_a_document_without_headings_says_so(self, run, monkeypatch, tmp_path):
        (tmp_path / "flat.md").write_text("just a paragraph\n", encoding="utf-8")
        monkeypatch.setenv("DC_DOCS", str(tmp_path))
        result = CliRunner().invoke(cli, ["outline", "flat"], catch_exceptions=False)
        assert "has no headings" in result.output

    def test_an_unknown_document_is_refused_with_a_hint(self, run):
        result = run("outline", "nope")
        assert result.exit_code != 0
        assert "no document 'nope'" in result.output


class TestCollapse:
    def test_matches_catalan_and_names_the_boundary(self, run):
        result = run("collapse", "--max-n", "6")
        assert result.exit_code == 0
        assert "132" in result.output
        assert "exactly Catalan(n) while n <= 6" in result.output
        assert "ordered forest" in result.output

    def test_shows_the_identity_breaking_at_seven(self, run):
        result = run("collapse", "--max-n", "7")
        row = next(
            ln for ln in result.output.splitlines() if ln.strip().startswith("7")
        )
        assert "428" in row
        assert "429" in row
        assert "differs" in row

    def test_states_the_concrete_collision(self, run):
        result = run("collapse", "--max-n", "2")
        assert "[1,3] and [1,2] produce the SAME tree" in result.output
        assert "Neither option is free" in result.output


class TestTable:
    def test_shows_the_invariant_and_both_policies(self, run):
        result = run("table", "h04-merged")
        assert result.exit_code == 0
        assert "9 grid positions, 8 cells" in result.output
        assert "-> True" in result.output
        assert "| Q1 | Q1 | Q2 |" in result.output
        assert "duplicated=1" in result.output
        assert "blanked=1" in result.output

    def test_says_why_the_loss_is_silent(self, run):
        result = run("table", "h04-merged")
        assert "distinct-value SET unchanged" in result.output
        assert "The source said neither" in result.output

    def test_a_ragged_table_reports_no_grid(self, run):
        result = run("table", "h06-ragged")
        assert "no grid exists" in result.output
        assert "padded=" in result.output

    def test_a_rowspan_table_is_rectangular(self, run):
        result = run("table", "h05-rowspan")
        assert "shape rectangular" in result.output

    def test_a_document_without_tables_says_so(self, run):
        result = run("table", "h01-clean")
        assert "has no tables" in result.output


class TestEncoding:
    def test_leads_with_the_consequence(self, run):
        result = run("encoding")
        assert result.exit_code == 0
        assert "latin-1 rejects 0 of 256 byte values" in result.output
        assert "never a necessity" in result.output

    def test_shows_the_asymmetry(self, run):
        result = run("encoding")
        assert "The wrong answer keeps every byte" in result.output
        assert "cp1252 (wrong)" in result.output

    def test_shows_the_competing_readings(self, run):
        result = run("encoding")
        assert "PREFERRED, not detected" in result.output
        assert "mac-roman" in result.output

    def test_surveys_the_corpus_and_repairs_mojibake(self, run):
        result = run("encoding")
        assert "h11-mojibake.html" in result.output
        assert "h12-cp1252.html" in result.output
        assert "h13-mojibake-whole.html" in result.output
        assert "repaired" in result.output
        assert "would call this clean" in result.output


class TestConvert:
    def test_emits_and_names_what_was_lost(self, run):
        result = run("convert", "h04-merged")
        assert result.exit_code == 0
        assert "| Q1 | Q1 | Q2 |" in result.output
        assert "merged_cell/invented x1" in result.output

    def test_the_same_document_to_wiki_loses_nothing(self, run):
        result = run("convert", "h04-merged", "--target", "wiki")
        assert 'colspan="2"' in result.output
        assert "this target holds every feature this document uses" in result.output

    def test_json_target_serialises_the_model(self, run):
        result = run("convert", "h01-clean", "--target", "json")
        payload_start = result.output.index("{")
        payload_end = result.output.rindex("}") + 1
        payload = json.loads(result.output[payload_start:payload_end])
        assert payload["source_format"] == "html"
        assert payload["blocks"][0]["kind"] == "heading"

    def test_an_unknown_target_is_refused(self, run):
        result = run("convert", "h01-clean", "--target", "pdf")
        assert result.exit_code != 0
        assert "unknown target" in result.output


class TestExplain:
    def test_shows_one_document_against_every_target(self, run):
        result = run("explain", "h04-merged")
        assert result.exit_code == 0
        for name in ("json", "markdown", "plain", "wiki"):
            assert name in result.output
        assert "merged_cell/invented" in result.output
        assert "BEFORE any conversion" in result.output

    def test_reports_the_encoding_note_when_there_is_one(self, run):
        result = run("explain", "h12-cp1252")
        assert "not valid UTF-8" in result.output
        assert "PREFERRED" in result.output

    def test_reports_heading_skips(self, run):
        result = run("explain", "h03-starts-deep")
        assert "heading skips: 1" in result.output
        assert "0 -> 3" in result.output
