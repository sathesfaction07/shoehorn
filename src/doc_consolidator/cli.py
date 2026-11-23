"""CLI.

Exit codes are deliberate. `check` fails only on things fixable AT SOURCE -- a file no
parser claims, or bytes someone chose to discard. It does NOT fail on a merged cell or a
heading skip, because those are properties of real documents, and a gate that fires whenever
somebody writes a spanning header in Word gets switched off inside a week.
"""

from __future__ import annotations

import json as jsonlib
import sys
from pathlib import Path

import click

from .config import Settings
from .emit import census, emit
from .encoding import (
    LEGACY_CODECS,
    candidate_decodings,
    compare_handlers,
    decode_bytes,
    no_undecodable_bytes,
    repair_mojibake,
)
from .formats import TARGETS, best_target, ceiling, unverifiable_claims, verify_claims
from .measure import build_report, compare_targets, decode_survey
from .models import Expressiveness, Feature, Fidelity
from .outline import (
    MAX_LEVEL,
    Reading,
    build_outline,
    collapse_census,
    depth_signature,
    find_skips,
    implied_nodes,
    max_depth,
)
from .parse import PARSERS, parse_file
from .render import ceiling_table, feature_breakdown, loss_table, matrix_table
from .tables import FlattenPolicy, distinct_values, flatten, occupancy


def _settings() -> Settings:
    return Settings()


def _find(docs: Path, doc_id: str) -> Path:
    for path in sorted(docs.iterdir()):
        if path.is_file() and path.stem == doc_id:
            return path
    raise click.ClickException(
        f"no document {doc_id!r} in {docs}; try `shoehorn report`"
    )


@click.group()
def cli() -> None:
    """Consolidate documents, and report what the TARGET format could not hold."""


@cli.command()
def doctor() -> None:
    """Configuration, targets, and which claims in the matrix are weaker than the rest."""
    settings = _settings()
    click.echo("configuration")
    click.echo(f"  docs        {settings.docs}")
    click.echo(f"  target      {settings.target}")
    click.echo(f"  reading     {settings.reading.value}")
    click.echo(f"  policy      {settings.policy.value}")

    click.echo("\nparsers (routed by EXTENSION, which is declared metadata not sniffed)")
    for suffix, kind in sorted(PARSERS.items()):
        click.echo(f"  {suffix:8} -> {kind}")

    click.echo("\ncapability matrix")
    problems = verify_claims()
    if problems:
        for problem in problems:
            click.echo(f"  BROKEN: {problem}")
    else:
        click.echo("  every claim carries a reason, and the arithmetic ones re-derive")

    weak = unverifiable_claims()
    click.echo(
        f"\n{len(weak)} claims rest on IMPLEMENTATION behaviour rather than grammar,"
    )
    click.echo("shown separately so they do not look as solid as the rest:")
    for name, feature, reason in weak:
        click.echo(f"  {name}/{feature.value}: {reason}")

    rejected, total = no_undecodable_bytes()
    click.echo(f"\nencoding: latin-1 rejects {rejected} of {total} byte values")
    click.echo(
        "  so no byte sequence is undecodable, and every errors='replace' is a CHOICE"
    )
    click.echo(f"  codecs consulted: {', '.join(LEGACY_CODECS)}")

    click.echo("\nvocabulary")
    click.echo("  Fidelity       " + ", ".join(f.value for f in Fidelity))
    click.echo("  Expressiveness " + ", ".join(e.value for e in Expressiveness))
    click.echo("  INVENTED and DROPPED are the two a `lossy: bool` collapses:")
    click.echo("  one ADDS content the source never had, the other REMOVES content it did")


@cli.command()
def matrix() -> None:
    """The capability matrix: what each target format can express."""
    click.echo("What each target format can hold. A property of the GRAMMAR, so no")
    click.echo("parser, OCR service or model moves any of it.\n")
    click.echo(matrix_table())
    click.echo(
        "\nThe row that matters is merged_cell: wiki yes, markdown NO. A pipe row holds"
    )
    click.echo(
        "exactly `cols` cells, so a spanning cell must become one cell (short row) or"
    )
    click.echo(
        "`span` cells (a value duplicated or blanked). Arithmetic, from the delimiters."
    )
    click.echo(
        "\nimage_text is ABSENT everywhere including json, because it is a property of"
    )
    click.echo("the SOURCE: the content is pixels, and this tool does not OCR.")


@cli.command()
@click.option("--target", default=None, help="Target format.")
@click.option("-o", "--out", type=click.Path(path_type=Path), default=None)
def report(target: str | None, out: Path | None) -> None:
    """Per-document losses for one target."""
    settings = _settings()
    chosen = target or settings.target
    if chosen not in TARGETS:
        raise click.ClickException(f"unknown target {chosen!r}; known: {sorted(TARGETS)}")

    rep = build_report(settings.docs, chosen, settings.reading, settings.policy)
    rate = rep.fidelity_rate

    click.echo(f"target {chosen}, reading {rep.reading.value}, policy {rep.policy.value}")
    click.echo(
        f"{len(rep.docs)} documents, {rep.total_features} feature instances, "
        f"{rep.total_lost} lost"
    )
    click.echo(
        "structural fidelity: "
        + (f"{rate:.1%}" if rate is not None else "n/a (nothing to measure)")
    )
    click.echo(f"by fidelity: {rep.by_fidelity or '{}'}")

    click.echo("\nper document")
    click.echo(loss_table(rep))

    click.echo("\nwhat was lost")
    click.echo(feature_breakdown(rep))

    silent = rep.silent_docs
    click.echo(
        f"\nSILENT: {len(silent)} of {len(rep.docs)} documents lost structure while the"
    )
    click.echo("set of text values stayed identical, so a content check passes:")
    for doc_id in silent:
        doc = next(d for d in rep.docs if d.doc_id == doc_id)
        first = doc.losses[0]
        click.echo(
            f"  {doc_id:26} {first.feature.value}/{first.fidelity.value} "
            f"x{first.count} -- values {doc.values_before} both sides"
        )
    click.echo(
        "\nThat is the spec's two questions coming apart: 'did we get all the content'"
    )
    click.echo("can be YES while 'did we preserve structure' is NO, and the first")
    click.echo("question's checker cannot see the second question's failure.")

    if rep.unreadable:
        click.echo(f"\nunreadable ({len(rep.unreadable)}): {', '.join(rep.unreadable)}")

    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        payload = {
            "target": rep.target,
            "reading": rep.reading.value,
            "policy": rep.policy.value,
            "documents": len(rep.docs),
            "total_features": rep.total_features,
            "total_lost": rep.total_lost,
            "fidelity_rate": rate,
            "by_fidelity": rep.by_fidelity,
            "silent_docs": list(silent),
            "unreadable": list(rep.unreadable),
            "encoding_counts": rep.encoding_counts,
            "unrecoverable": list(rep.unrecoverable),
            "ceiling": {k: list(v) for k, v in rep.ceiling_table.items()},
            "docs": [
                {
                    "doc_id": d.doc_id,
                    "source_format": d.source_format,
                    "features": d.features,
                    "lost": d.lost_instances,
                    "content_changed": d.content_changed,
                    "values_before": d.values_before,
                    "values_after": d.values_after,
                    "is_silent": d.is_silent,
                    "decoding": d.decoding.value,
                    "skips": d.skips,
                    "declared_depth": d.declared_depth,
                    "read_depth": d.read_depth,
                    "losses": [
                        {
                            "feature": lo.feature.value,
                            "fidelity": lo.fidelity.value,
                            "count": lo.count,
                            "detail": lo.detail,
                        }
                        for lo in d.losses
                    ],
                }
                for d in rep.docs
            ],
        }
        (out / "report.json").write_text(
            jsonlib.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        click.echo(f"\nwrote {out / 'report.json'}")

    if not rep.is_clean:
        sys.exit(1)


@cli.command()
def compare() -> None:
    """Every target over the same corpus. The comparison IS the argument."""
    settings = _settings()
    reports = compare_targets(settings.docs, settings.reading, settings.policy)
    any_report = next(iter(reports.values()))

    click.echo("Same parsers, same tree, same policy -- only the target differs.")
    click.echo("So every difference below belongs to the FORMAT, not to the reader.\n")

    click.echo(f"  {'target':10}{'lost':>7}{'fidelity':>10}{'silent docs':>13}  by fidelity")
    click.echo("  " + "-" * 72)
    for name, rep in sorted(reports.items(), key=lambda kv: kv[1].total_lost):
        rate = rep.fidelity_rate
        click.echo(
            f"  {name:10}{rep.total_lost:>7}"
            f"{(f'{rate:.1%}' if rate is not None else 'n/a'):>10}"
            f"{len(rep.silent_docs):>13}  {rep.by_fidelity or '{}'}"
        )

    click.echo("\n" + ceiling_table(any_report))

    counts = any_report.corpus_census
    target, lost = best_target(counts)
    click.echo(f"\nfewest losses: {target} ({lost})")
    click.echo(
        "json usually wins, and that is reported rather than hidden. A tool that"
    )
    click.echo(
        "steered a reader to a prettier format knowing it drops content would be"
    )
    click.echo("choosing presentation on their behalf.")

    md = reports["markdown"]
    wiki = reports["wiki"]
    click.echo(
        f"\nmarkdown loses {md.total_lost} where wiki loses {wiki.total_lost}, on the same"
    )
    click.echo("documents. The gap is almost entirely merged cells: markdown has no")
    click.echo("construct for one and wiki carries HTML attributes on a cell.")


@cli.command()
def check() -> None:
    """Gate on what is fixable at source. Exit 1 on an unreadable file or discarded bytes."""
    settings = _settings()
    rep = build_report(settings.docs, settings.target, settings.reading, settings.policy)

    click.echo(f"{len(rep.docs)} documents read from {settings.docs}")
    click.echo(f"encoding: {rep.encoding_counts}")

    failures: list[str] = []
    if rep.unreadable:
        failures.append(f"no parser for {len(rep.unreadable)}: {', '.join(rep.unreadable)}")
    if rep.unrecoverable:
        failures.append(
            f"bytes discarded in {len(rep.unrecoverable)}: {', '.join(rep.unrecoverable)}"
        )

    problems = verify_claims()
    if problems:
        failures.extend(f"capability matrix: {p}" for p in problems)

    skips = sum(d.skips for d in rep.docs)
    silent = len(rep.silent_docs)
    merged = rep.corpus_census.get(Feature.MERGED_CELL, 0)
    mojibake = rep.encoding_counts.get("mojibake", 0)

    click.echo("\nReported and NOT failed on, because these are properties of real")
    click.echo("documents rather than defects anyone can fix at source:")
    click.echo(f"  heading skips:              {skips}")
    click.echo(f"  merged-cell grid positions: {merged}")
    click.echo(f"  silent structural losses:   {silent}")
    click.echo(f"  documents with mojibake:    {mojibake} (recoverable)")
    click.echo(
        "\nA gate that fired whenever somebody wrote a spanning header in Word would"
    )
    click.echo("be switched off inside a week.")

    if failures:
        click.echo("\nFAIL")
        for failure in failures:
            click.echo(f"  {failure}")
        sys.exit(1)
    click.echo("\nPASS")


@cli.command()
@click.argument("doc_id")
def outline(doc_id: str) -> None:
    """One document's headings under BOTH readings, which disagree."""
    settings = _settings()
    doc = parse_file(_find(settings.docs, doc_id))
    headings = doc.headings

    if not headings:
        click.echo(f"{doc_id} has no headings")
        return

    click.echo(f"{doc_id}: {len(headings)} headings, declared levels "
               f"{[h.level for h in headings]}")

    skips = find_skips(headings)
    if skips:
        click.echo(f"\n{len(skips)} skip(s):")
        for skip in skips:
            click.echo(
                f"  level {skip.from_level} -> {skip.to_level} "
                f"(gap {skip.gap}) at {skip.text[:40]!r}"
            )
    else:
        click.echo("\nno skips, so both readings agree")

    click.echo("\nthe two readings")
    for reading in Reading:
        forest = build_outline(headings, reading)
        click.echo(
            f"  {reading.value:9} depth={max_depth(forest)} "
            f"implied_nodes={implied_nodes(forest)} signature={depth_signature(forest)}"
        )
        for root in forest:
            for node in root.walk():
                label = "(implied)" if node.is_implied else node.text[:40]
                declared = "-" if node.declared_level is None else node.declared_level
                click.echo(
                    f"      {'  ' * (node.depth - 1)}depth {node.depth} "
                    f"declared {declared}  {label}"
                )

    click.echo("\nNeither is a fix. Both are decisions about what the author meant, and")
    click.echo("nothing in the source says which. PROMOTE discards the declared numbers;")
    click.echo("IMPLICIT keeps them and adds nodes the document never contained.")


@cli.command()
@click.option("--max-n", default=6, show_default=True)
def collapse(max_n: int) -> None:
    """How much information the flat-levels-to-outline map destroys. Brute forced."""
    from math import comb

    click.echo("A document declares headings as a flat sequence of numbers. An outline is")
    click.echo("a tree. The map between them is NOT injective, so different documents")
    click.echo("produce identical outlines.\n")

    click.echo(f"  {'n':>2}{'sequences':>11}{'promote':>9}{'Catalan(n)':>12}"
               f"{'implicit':>10}{'collapse':>10}")
    click.echo("  " + "-" * 54)
    for n in range(1, max_n + 1):
        total, promote = collapse_census(n, Reading.PROMOTE)
        _, implicit = collapse_census(n, Reading.IMPLICIT)
        catalan = comb(2 * n, n) // (n + 1)
        mark = "" if promote == catalan else "  <- differs"
        click.echo(
            f"  {n:>2}{total:>11}{promote:>9}{catalan:>12}{implicit:>10}"
            f"{total / promote:>9.1f}x{mark}"
        )

    click.echo(
        f"\nUnder PROMOTE the count is exactly Catalan(n) while n <= {MAX_LEVEL}, because a"
    )
    click.echo("promote-normalised outline IS an ordered forest on n nodes and ordered")
    click.echo(f"forests are counted by Catalan numbers. At n = {MAX_LEVEL + 1} it falls")
    click.echo("short by exactly one: the single depth-7 chain, which 6 heading levels")
    click.echo("cannot express.")
    click.echo("\n[1,3] and [1,2] produce the SAME tree. That is the loss, concretely.")
    click.echo("IMPLICIT collapses far less -- it keeps the declared numbers -- and pays")
    click.echo("for it by inventing nodes. Neither option is free.")


@cli.command()
@click.argument("doc_id")
def table(doc_id: str) -> None:
    """A document's tables, and the two ways to write a merged cell into a grid."""
    settings = _settings()
    doc = parse_file(_find(settings.docs, doc_id))
    tables = [b for b in doc.walk() if b.kind == "table"]

    if not tables:
        click.echo(f"{doc_id} has no tables")
        return

    for index, block in enumerate(tables):
        rows = tuple(r.cells for r in block.children if r.kind == "row")
        occ = occupancy(rows)
        click.echo(
            f"table {index}: {occ.rows}x{occ.cols} = {occ.positions} grid positions, "
            f"{occ.cell_count} cells, shape {occ.shape.value}"
        )
        click.echo(
            f"  invariant sum(colspan*rowspan) == rows*cols: "
            f"{occ.covered_positions} vs {occ.positions} -> "
            f"{occ.covered_positions == occ.positions}"
        )
        if occ.holes or occ.overlaps:
            click.echo(f"  holes {occ.holes}, overlaps {occ.overlaps} -- no grid exists")
        click.echo(f"  positions that exist only because something spans: {occ.merged_cells}")

        for policy in FlattenPolicy:
            flat = flatten(rows, policy)
            click.echo(f"\n  {policy.value}")
            for row in flat.grid:
                click.echo("    | " + " | ".join(v or " " for v in row) + " |")
            click.echo(
                f"    duplicated={flat.duplicated_positions} "
                f"blanked={flat.blanked_positions} padded={flat.padded_positions} "
                f"faithful={flat.is_faithful}"
            )
            click.echo(f"    distinct values in the grid: {distinct_values(flat.grid)}")

        if occ.merged_cells:
            click.echo(
                "\n  Both policies leave the distinct-value SET unchanged, so a checker"
            )
            click.echo(
                "  comparing values read against values written passes either way."
            )
            click.echo(
                "  DUPLICATE asserts two columns carried the same label; BLANK asserts"
            )
            click.echo("  one column had no label. The source said neither.")
        click.echo("")


@cli.command()
def encoding() -> None:
    """The decode survey, and why the careful-looking handler is the lossy one."""
    settings = _settings()

    rejected, total = no_undecodable_bytes()
    click.echo(f"latin-1 rejects {rejected} of {total} byte values.")
    click.echo("So there is no such thing as undecodable bytes, and every")
    click.echo("errors='replace' is a CHOICE to discard information, never a necessity.\n")

    click.echo("the three handlers, on b'caf\\xe9'")
    click.echo(f"  {'handler':18}{'result':16}recoverable")
    click.echo("  " + "-" * 46)
    for handler, (text, recoverable) in compare_handlers(b"caf\xe9").items():
        click.echo(f"  {handler:18}{text!r:16}{recoverable}")
    click.echo("\nThe wrong answer keeps every byte. The safe-looking one destroys them.")

    click.echo("\ncompeting readings for the same bytes")
    for candidate, text in candidate_decodings(b"caf\xe9").items():
        click.echo(f"  {candidate:11} {text!r}")
    click.echo("  cp1252 is PREFERRED, not detected. Nothing in the bytes says which.")

    click.echo("\ncorpus survey")
    click.echo(f"  {'document':28}{'verdict':11}{'readings':>9}  recoverable")
    click.echo("  " + "-" * 62)
    for name, verdict, candidates, recoverable in decode_survey(settings.docs):
        if verdict.value == "clean":
            continue
        click.echo(f"  {name:28}{verdict.value:11}{candidates:>9}  {recoverable}")

    for name, verdict, _c, _r in decode_survey(settings.docs):
        if verdict.value != "mojibake":
            continue
        path = settings.docs / name
        result = decode_bytes(path.read_bytes())
        click.echo(f"\n  {name}")
        click.echo(f"    {result.detail}")
        repaired = repair_mojibake(result.text)
        if repaired is not None:
            changed = [
                line.strip()
                for before, line in zip(
                    result.text.splitlines(), repaired.splitlines(), strict=False
                )
                if before != line
            ]
            click.echo(f"    repaired {len(changed)} line(s), e.g. {changed[0][:60]!r}")

    click.echo(
        "\nA partially mis-decoded document defeats a whole-text round trip, because"
    )
    click.echo(
        "one correctly-encoded character breaks it. Scanned line by line instead."
    )


@cli.command()
@click.argument("doc_id")
@click.option("--target", default=None)
def convert(doc_id: str, target: str | None) -> None:
    """Emit one document, then say what the target could not hold."""
    settings = _settings()
    chosen = target or settings.target
    if chosen not in TARGETS:
        raise click.ClickException(f"unknown target {chosen!r}; known: {sorted(TARGETS)}")

    doc = parse_file(_find(settings.docs, doc_id))
    text, losses = emit(doc, chosen, settings.reading, settings.policy)

    click.echo(f"--- {doc_id} as {chosen} ---")
    click.echo(text.rstrip())
    click.echo(f"--- {len(losses)} loss(es) ---")
    for loss in losses:
        click.echo(f"  {loss.feature.value}/{loss.fidelity.value} x{loss.count}")
        click.echo(f"    {loss.detail}")
    if not losses:
        click.echo("  nothing -- this target holds every feature this document uses")


@cli.command()
@click.argument("doc_id")
def explain(doc_id: str) -> None:
    """One document across every target."""
    settings = _settings()
    doc = parse_file(_find(settings.docs, doc_id))
    counts = census(doc)

    click.echo(f"{doc_id} ({doc.source_format})")
    click.echo(f"  features: { {f.value: n for f, n in counts.items()} }")
    if doc.encoding_note:
        click.echo(f"  encoding: {doc.encoding_note}")

    skips = find_skips(doc.headings)
    if skips:
        click.echo(f"  heading skips: {len(skips)}")
        for skip in skips:
            click.echo(f"    {skip.from_level} -> {skip.to_level} at {skip.text[:40]!r}")

    click.echo(f"\n  {'target':10}{'survives':>10}{'lost':>7}  losses")
    click.echo("  " + "-" * 60)
    for name in sorted(TARGETS):
        survives, lost = ceiling(name, counts)
        _text, losses = emit(doc, name, settings.reading, settings.policy)
        detail = ", ".join(
            f"{lo.feature.value}/{lo.fidelity.value}" for lo in losses
        )
        click.echo(f"  {name:10}{survives:>10}{lost:>7}  {detail or '-'}")

    click.echo("\n  The ceiling column is computed from the census and the target name")
    click.echo("  alone, BEFORE any conversion. No parser changes it.")


if __name__ == "__main__":
    cli()
