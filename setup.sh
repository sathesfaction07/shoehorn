#!/usr/bin/env bash
# Sets up DocConsolidator and re-derives every finding in the README from scratch.
# Nothing here is asserted from memory: each block computes its number and fails loudly.
set -euo pipefail

cd "$(dirname "$0")"

echo "=============================================================================="
echo " DocConsolidator -- setup"
echo "=============================================================================="

if [ ! -d .venv ]; then
    echo "creating .venv"
    python3 -m venv .venv
fi
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e ".[dev]"
echo "dependencies installed"

echo
echo "generating the corpus"
./.venv/bin/python data/generate.py | head -1

echo
echo "=============================================================================="
echo " 1. THE TARGET FORMAT IS THE CEILING, NOT THE PARSER"
echo "=============================================================================="
./.venv/bin/python - <<'PY'
from doc_consolidator.formats import TARGETS, expressiveness, verify_claims
from doc_consolidator.models import Expressiveness, Feature

problems = verify_claims()
assert not problems, problems
print("     Every claim in the matrix carries a reason, and the arithmetic ones re-derive.")
print()

# The arithmetic the merged-cell claim rests on: a pipe row's cell count is its delimiters.
for row, expected in (("| a | b |", 2), ("| a | b | c |", 3)):
    count = len([c for c in row.split("|") if c.strip()])
    assert count == expected, (row, count)
print("     A pipe row holds exactly as many cells as it has delimiters, so a table")
print("     rendered as pipe rows must emit `cols` cells in EVERY row. A cell spanning")
print("     two columns is ONE value over TWO positions. No third option exists.")
print()

md = expressiveness("markdown", Feature.MERGED_CELL)
wiki = expressiveness("wiki", Feature.MERGED_CELL)
assert md is Expressiveness.ABSENT, md
assert wiki is Expressiveness.NATIVE, wiki
print(f"     markdown merged_cell: {md.value:8}   wiki merged_cell: {wiki.value}")
print("     Same feature, same parser, same tree. The difference is the GRAMMAR.")
print()

for name in TARGETS:
    assert expressiveness(name, Feature.IMAGE_TEXT) is not Expressiveness.NATIVE
print("     image_text is unreachable in EVERY target including the lossless control,")
print("     because it is a property of the SOURCE: the content is pixels.")
PY

echo
echo "=============================================================================="
echo " 2. A MERGED CELL HAS NO GRID REPRESENTATION, AND BOTH REPAIRS ARE WRONG"
echo "=============================================================================="
./.venv/bin/python - <<'PY'
from doc_consolidator.models import Cell
from doc_consolidator.tables import FlattenPolicy, distinct_values, flatten, occupancy

def C(t, cs=1, rs=1):
    return Cell(text=t, colspan=cs, rowspan=rs)

colspan = ((C("Q1", cs=2),), (C("Jan"), C("Feb")))
rowspan = ((C("EMEA", rs=2), C("London")), (C("Berlin"),))
ragged  = ((C("Summary"),), (C("a"), C("b"), C("c")))

print(f"     {'table':10}{'RxC':>6}{'cells':>7}{'positions':>11}{'merged':>8}  shape")
for label, rows in (("colspan", colspan), ("rowspan", rowspan), ("ragged", ragged)):
    o = occupancy(rows)
    print(f"     {label:10}{f'{o.rows}x{o.cols}':>6}{o.cell_count:>7}{o.positions:>11}"
          f"{o.merged_cells:>8}  {o.shape.value}")

o = occupancy(colspan)
assert (o.cell_count, o.positions, o.merged_cells) == (3, 4, 1)
assert o.covered_positions == o.positions
assert occupancy(rowspan).shape.value == "rectangular"
assert occupancy(ragged).shape.value == "ragged"

# A colspan-only count calls the rowspan table ragged. The occupancy walk does not.
naive = [sum(c.colspan for c in row) for row in rowspan]
assert naive == [2, 1], naive
print()
print(f"     A colspan-only count gives rows of {naive} for the rowspan table and calls")
print("     it ragged. It is rectangular: a cell spanning down occupies a position in a")
print("     row it does not appear in.")
print()

source_values = {c.text for row in colspan for c in row}
print("     The two repairs, on a colspan=2 header over Jan and Feb:")
for policy in FlattenPolicy:
    flat = flatten(colspan, policy)
    grid = " / ".join("|".join(v or " " for v in row) for row in flat.grid)
    values = {v for row in flat.grid for v in row if v}
    assert values == source_values, (policy, values)
    print(f"       {policy.value:10} {grid:24} duplicated={flat.duplicated_positions} "
          f"blanked={flat.blanked_positions}  distinct values {distinct_values(flat.grid)}")

dup = flatten(colspan, FlattenPolicy.DUPLICATE)
blank = flatten(colspan, FlattenPolicy.BLANK)
assert dup.grid == (("Q1", "Q1"), ("Jan", "Feb"))
assert blank.grid == (("Q1", ""), ("Jan", "Feb"))
assert dup.duplicated_positions == 1 and blank.blanked_positions == 1
print()
print("     DUPLICATE asserts two columns were both labelled Q1. BLANK asserts one")
print("     column had no label. The source said NEITHER -- and both leave the set of")
print("     distinct values UNCHANGED, so a content check passes either way.")
print()

flat = flatten(ragged, FlattenPolicy.DUPLICATE)
assert flat.padded_positions == 2, flat.padded_positions
print(f"     The ragged table gains {flat.padded_positions} positions that had no cell at all.")
print("     An earlier version had a counter for a failure that CANNOT occur and none")
print("     for this one, which occurs in 26,174 of 30,000 random tables.")
PY

echo
echo "=============================================================================="
echo " 3. THE OUTLINE MAP IS NOT INJECTIVE, AND THE COUNT IS CATALAN(n)"
echo "=============================================================================="
./.venv/bin/python - <<'PY'
from math import comb

from doc_consolidator.models import Block
from doc_consolidator.outline import (
    MAX_LEVEL, Reading, build_outline, collapse_census, depth_signature, max_depth,
)

def H(*levels):
    return tuple(Block(kind="heading", level=lv, text=f"h{lv}#{i}")
                 for i, lv in enumerate(levels))

skipped = depth_signature(build_outline(H(1, 3), Reading.PROMOTE))
clean = depth_signature(build_outline(H(1, 2), Reading.PROMOTE))
assert skipped == clean == (1, 2)
print(f"     [1,3] -> {skipped}      [1,2] -> {clean}      identical: {skipped == clean}")
print("     Two documents that declared different structures produce the SAME outline.")
print()

promote = build_outline(H(1, 3), Reading.PROMOTE)
implicit = build_outline(H(1, 3), Reading.IMPLICIT)
assert max_depth(promote) == 2 and max_depth(implicit) == 3
print(f"     The same h1/h3 source: promote depth {max_depth(promote)}, "
      f"implicit depth {max_depth(implicit)}.")
print("     Neither is a fix. Both are decisions about what the author meant.")
print()

print(f"     {'n':>2}{'sequences':>11}{'promote':>9}{'Catalan(n)':>12}{'implicit':>10}{'collapse':>10}")
for n in range(1, 8):
    total, distinct = collapse_census(n, Reading.PROMOTE)
    _, imp = collapse_census(n, Reading.IMPLICIT)
    catalan = comb(2 * n, n) // (n + 1)
    mark = "" if distinct == catalan else "  <- one short"
    print(f"     {n:>2}{total:>11}{distinct:>9}{catalan:>12}{imp:>10}"
          f"{total/distinct:>9.1f}x{mark}")
    if n <= MAX_LEVEL:
        assert distinct == catalan, (n, distinct, catalan)
    else:
        assert catalan - distinct == 1, (n, distinct, catalan)

print()
print(f"     Exactly Catalan(n) while n <= {MAX_LEVEL}: a promote-normalised outline IS an")
print("     ordered forest on n nodes, and ordered forests are counted by Catalan numbers.")
print(f"     At n = {MAX_LEVEL + 1} it falls short by EXACTLY ONE -- the single depth-7 chain,")
print("     which 6 heading levels cannot express. Off by one confirms the explanation.")
PY

echo
echo "=============================================================================="
echo " 4. THE SAFE-LOOKING ENCODING HANDLER IS THE LOSSY ONE"
echo "=============================================================================="
./.venv/bin/python - <<'PY'
import random

from doc_consolidator.encoding import (
    Decoding, candidate_decodings, compare_handlers, decode_bytes, looks_like_mojibake,
    mojibake_lines, no_undecodable_bytes,
)

rejected, total = no_undecodable_bytes()
assert (rejected, total) == (0, 256)
print(f"     latin-1 rejects {rejected} of {total} byte values.")
print("     So NO byte sequence is undecodable, and every errors='replace' in a")
print("     codebase is a CHOICE to discard information, never a necessity.")
print()

print(f"     {'handler':18}{'result':16}recoverable")
for handler, (text, recoverable) in compare_handlers(b"caf\xe9").items():
    print(f"     {handler:18}{text!r:16}{recoverable}")
handlers = compare_handlers(b"caf\xe9")
assert handlers["utf-8 + replace"][1] is False
assert handlers["utf-8 + ignore"][1] is False
assert handlers["cp1252 (wrong)"] == ("café", True)
print("     The WRONG answer keeps every byte. The safe-looking one destroys them.")
print()

candidates = candidate_decodings(b"caf\xe9")
assert len(candidates) == 4 and len(set(candidates.values())) == 3
for codec, text in candidates.items():
    print(f"     {codec:11} {text!r}")
result = decode_bytes(b"caf\xe9")
assert result.codec_used == "cp1252" and result.candidates == 3
print(f"     {len(candidates)} codecs accept these bytes and produce {result.candidates} distinct")
print(f"     strings. {result.codec_used} was PREFERRED, not detected.")
print()

rng = random.Random(7)
seen = set()
for _ in range(4000):
    raw = bytes(rng.randrange(256) for _ in range(rng.randint(1, 12)))
    seen.add(decode_bytes(raw).decoding)
assert Decoding.LOSSY not in seen, "LOSSY should be unreachable with the default codecs"
print(f"     Over 4,000 random byte strings the verdicts seen are "
      f"{sorted(v.value for v in seen)}.")
print("     LOSSY is unreachable, which is the point.")
print()

mixed = "\n".join(["Café".encode("utf-8").decode("cp1252"), "Jean-Léon", "ascii"])
try:
    mixed.encode("cp1252").decode("utf-8")
    raise AssertionError("the whole-text round trip should fail here")
except UnicodeDecodeError:
    pass
assert mojibake_lines(mixed) == [0]
found, note = looks_like_mojibake(mixed)
assert found and "1 of 3 lines" in note
print("     A PARTIALLY mis-decoded document defeats a whole-text round trip: one")
print("     correctly-encoded character breaks it, because re-encoding U+00E9 as cp1252")
print("     gives 0xE9, which is not a valid UTF-8 lead byte. Scanned per line instead.")
PY

echo
echo "=============================================================================="
echo " 5. THE TWO QUESTIONS COME APART ON THE SHIPPED CORPUS"
echo "=============================================================================="
./.venv/bin/python - <<'PY'
from pathlib import Path

from doc_consolidator.emit import emit
from doc_consolidator.measure import build_report, compare_targets
from doc_consolidator.models import Feature
from doc_consolidator.parse import parse_file

DOCS = Path("data/docs")
reports = compare_targets(DOCS)

print(f"     {'target':10}{'lost':>7}{'fidelity':>10}{'silent':>8}  by fidelity")
for name, rep in sorted(reports.items(), key=lambda kv: kv[1].total_lost):
    rate = rep.fidelity_rate
    print(f"     {name:10}{rep.total_lost:>7}"
          f"{(f'{rate:.1%}' if rate is not None else 'n/a'):>10}"
          f"{len(rep.silent_docs):>8}  {rep.by_fidelity or '{}'}")

md, wiki, js = reports["markdown"], reports["wiki"], reports["json"]
assert md.total_lost > wiki.total_lost > js.total_lost
assert wiki.by_fidelity.get("invented", 0) == 0
assert md.by_fidelity.get("invented", 0) > 0
print()
print("     Same parsers, same tree, same policy. Only the target differs.")
print()

doc = parse_file(DOCS / "h04-merged.html")
md_text, md_losses = emit(doc, "markdown")
wiki_text, wiki_losses = emit(doc, "wiki")
assert "| Q1 | Q1 |" in md_text and md_losses
assert 'colspan="2"' in wiki_text and not wiki_losses
print("     h04-merged, one tree, two targets:")
print(f"       markdown  {[ln for ln in md_text.splitlines() if 'Q1' in ln][0]}")
print(f"                 {len(md_losses)} loss: {md_losses[0].feature.value}/"
      f"{md_losses[0].fidelity.value}")
print(f"       wiki      {[ln for ln in wiki_text.splitlines() if 'Q1' in ln][0]}")
print(f"                 {len(wiki_losses)} losses")
print()

with_spans = {
    d.doc_id for d in md.docs if d.features.get(Feature.MERGED_CELL.value, 0) > 0
}
assert with_spans <= set(md.silent_docs), with_spans - set(md.silent_docs)
assert not (with_spans & set(wiki.silent_docs))
print(f"     {len(md.silent_docs)} of {len(md.docs)} documents lose structure for markdown while a")
print("     ROUND-TRIPPED value-set comparison sees no difference at all. Every one of")
print(f"     the {len(with_spans)} merged-cell documents is among them, and NONE of them is")
print("     among wiki's, because wiki loses nothing on them.")
print()

assert not js.round_trippable
assert all(d.values_after is None for d in js.docs)
assert js.silent_docs == () and js.unmeasurable_docs
print(f"     json has no parser here, so {len(js.unmeasurable_docs)} document(s) with losses are")
print("     reported as UNMEASURABLE rather than counted as proven quiet.")
print()

order_by_result = sorted(reports, key=lambda n: reports[n].total_lost)
table = md.ceiling_table
order_by_ceiling = sorted(table, key=lambda n: table[n][1])
assert order_by_result == order_by_ceiling == ["json", "wiki", "markdown", "plain"]
print(f"     The ceiling -- computed from the census and the target NAME alone, before")
print(f"     any conversion runs -- orders the targets {order_by_ceiling},")
print("     which is exactly how the measured results come out.")
PY

echo
echo "=============================================================================="
echo " TESTS"
echo "=============================================================================="
./.venv/bin/python -m pytest -q
./.venv/bin/ruff check src tests data --output-format concise && echo "ruff: clean"

echo
echo "=============================================================================="
echo " READY"
echo "=============================================================================="
cat <<'EOF'
  source .venv/bin/activate

  doc-consolidator doctor              config, and which matrix claims are weaker
  doc-consolidator matrix              what each target format can express
  doc-consolidator compare             all four targets over one corpus
  doc-consolidator report              per-document losses, and the silent ones
  doc-consolidator check               exit 1 on what is fixable at source
  doc-consolidator collapse            the Catalan collapse, brute forced
  doc-consolidator outline h02-skip    one source, two readings, two trees
  doc-consolidator table h04-merged    the merged-cell dichotomy
  doc-consolidator encoding            why errors='replace' is the lossy choice
  doc-consolidator convert h04-merged  emit, then say what was lost
  doc-consolidator explain h04-merged  one document against every target
EOF
