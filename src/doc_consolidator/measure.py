"""The report, and the signature it exists to surface.

The spec asks one question with two halves: "Did we extract ALL content correctly AND
preserve structure?" Those are separate questions, and the measurement that matters is that
**a checker for the first cannot see a failure of the second.**

Concretely: flattening a merged cell under DUPLICATE writes "Q1" into two grid positions.
The SET of text values is unchanged. So a converter that verifies its work by comparing the
values it read against the values it wrote passes -- and the output now asserts that two
columns were separately labelled Q1, which the source did not say.

That case is `silent` here: a structural loss with an unchanged value set. It is the
document-level analogue of a passing test that proves nothing.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .emit import census, emit
from .encoding import Decoding, decode_bytes
from .formats import TARGETS, ceiling
from .models import Document, Feature, FeatureLoss, Fidelity
from .outline import Reading, build_outline, find_skips, implied_nodes, max_depth
from .parse import PARSERS, parse_file, parse_markdown, parse_wiki
from .tables import FlattenPolicy


class DocReport(BaseModel):
    """One document against one target."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    source_format: str
    features: dict[str, int]
    losses: tuple[FeatureLoss, ...]
    decoding: Decoding
    decode_detail: str = ""
    skips: int
    declared_depth: int
    read_depth: int
    implied: int
    values_before: int
    values_after: int | None
    """Distinct text values in the source, and in the output AFTER RE-PARSING it.

    `int | None` -- None when the target has no parser here, so no round trip is possible
    and no comparison can be made. An earlier version compared source VALUES against output
    LINES, which are different quantities: a markdown table row is one line holding three
    values, so every document with a table produced a difference that meant nothing. It
    reported a plausible boolean and the merged-cell documents -- the whole point -- were
    missing from the list they should have headed."""

    @property
    def lost_instances(self) -> int:
        return sum(loss.count for loss in self.losses)

    @property
    def content_changed(self) -> int:
        return sum(loss.count for loss in self.losses if loss.changes_content)

    @property
    def values_preserved(self) -> bool | None:
        if self.values_after is None:
            return None
        return self.values_before == self.values_after

    @property
    def is_silent(self) -> bool:
        """Structure was lost and a round-tripped value-set comparison does not notice.

        The signature this project exists to name. Not the same as "harmless": the markdown
        output for the corpus's merged header reads as two columns both called Q1.
        """
        return bool(self.losses) and self.values_preserved is True

    @property
    def silence_unmeasurable(self) -> bool:
        """Structure was lost and this tool cannot round-trip the target to check.

        Kept separate from `is_silent` so a target with no parser is never counted as
        proven quiet. `all([])` being True is the same trap in a different costume.
        """
        return bool(self.losses) and self.values_after is None

    @property
    def reading_changed_structure(self) -> bool:
        return self.read_depth != self.declared_depth or self.implied > 0


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str
    reading: Reading
    policy: FlattenPolicy
    docs: tuple[DocReport, ...]
    unreadable: tuple[str, ...] = ()
    """Files no parser claimed, by name. Reported rather than skipped."""

    @property
    def corpus_census(self) -> dict[Feature, int]:
        total: dict[Feature, int] = {}
        for doc in self.docs:
            for name, count in doc.features.items():
                key = Feature(name)
                total[key] = total.get(key, 0) + count
        return total

    @property
    def total_features(self) -> int:
        return sum(self.corpus_census.values())

    @property
    def total_lost(self) -> int:
        return sum(doc.lost_instances for doc in self.docs)

    @property
    def by_fidelity(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for doc in self.docs:
            for loss in doc.losses:
                out[loss.fidelity.value] = out.get(loss.fidelity.value, 0) + loss.count
        return out

    @property
    def silent_docs(self) -> tuple[str, ...]:
        return tuple(d.doc_id for d in self.docs if d.is_silent)

    @property
    def unmeasurable_docs(self) -> tuple[str, ...]:
        """Documents that lost structure where no round trip is available to check."""
        return tuple(d.doc_id for d in self.docs if d.silence_unmeasurable)

    @property
    def round_trippable(self) -> bool:
        return self.target in ROUND_TRIPPABLE

    @property
    def fidelity_rate(self) -> float | None:
        """Share of feature instances that survived intact.

        `float | None` -- None when the corpus contains no structural features at all,
        because `0/0` is not 100%. An empty corpus has not been preserved perfectly; it has
        not been measured.
        """
        total = self.total_features
        if total == 0:
            return None
        return (total - self.total_lost) / total

    @property
    def ceiling_table(self) -> dict[str, tuple[int, int]]:
        """What each target would lose on this corpus, computed from the census alone.

        Available before any conversion runs, which is what makes it a ceiling: no change of
        parser, OCR service or model moves any of these numbers.
        """
        counts = self.corpus_census
        return {name: ceiling(name, counts) for name in TARGETS}

    @property
    def encoding_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for doc in self.docs:
            out[doc.decoding.value] = out.get(doc.decoding.value, 0) + 1
        return out

    @property
    def unrecoverable(self) -> tuple[str, ...]:
        """Documents whose bytes cannot be reconstructed. Should be empty -- see
        `no_undecodable_bytes`: nothing is genuinely undecodable, so a non-empty list here
        means someone chose to discard information."""
        return tuple(d.doc_id for d in self.docs if d.decoding is Decoding.LOSSY)

    @property
    def is_clean(self) -> bool:
        return not self.unreadable and not self.unrecoverable


# Targets this tool can read back. json and plain are absent deliberately: a round trip
# through them would need a parser this project does not have, and inventing a line-based
# proxy is what produced the meaningless comparison described on `values_after`.
ROUND_TRIPPABLE = {"markdown": parse_markdown, "wiki": parse_wiki}


def _distinct_values(doc: Document) -> int:
    return len({line for line in doc.text_content.splitlines() if line.strip()})


def _values_after_round_trip(text: str, target: str) -> int | None:
    """Distinct values recoverable by re-parsing the output, or None if we cannot.

    A real round trip, so the comparison is value-set against value-set. This is the only
    honest way to answer "would a content check have noticed": it runs the content check.
    """
    parser = ROUND_TRIPPABLE.get(target)
    if parser is None:
        return None
    return _distinct_values(parser(text.encode("utf-8"), "round-trip"))


def analyse(
    doc: Document,
    target: str,
    reading: Reading = Reading.PROMOTE,
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> DocReport:
    counts = census(doc)
    text, losses = emit(doc, target, reading, policy)

    declared = max((h.level or 1) for h in doc.headings) if doc.headings else 0
    forest = build_outline(doc.headings, reading)

    return DocReport(
        doc_id=doc.doc_id,
        source_format=doc.source_format,
        features={f.value: n for f, n in counts.items()},
        losses=tuple(losses),
        decoding=_decoding_of(doc),
        decode_detail=doc.encoding_note,
        skips=len(find_skips(doc.headings)),
        declared_depth=declared,
        read_depth=max_depth(forest),
        implied=implied_nodes(forest),
        values_before=_distinct_values(doc),
        values_after=_values_after_round_trip(text, target),
    )


def _decoding_of(doc: Document) -> Decoding:
    """Recover the decode verdict from the note the parser attached.

    Carried as a note on the Document rather than as an enum because a Document should not
    need to know about this module. The mapping is on the substrings the detail strings are
    built from, which is fragile enough to be worth a test.
    """
    note = doc.encoding_note
    if not note:
        return Decoding.CLEAN
    if "unrecoverable" in note:
        return Decoding.LOSSY
    if "already mis-decoded" in note:
        return Decoding.MOJIBAKE
    if "not valid UTF-8" in note:
        return Decoding.AMBIGUOUS
    return Decoding.CLEAN


def build_report(
    directory: Path,
    target: str,
    reading: Reading = Reading.PROMOTE,
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> Report:
    docs: list[DocReport] = []
    unreadable: list[str] = []

    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in PARSERS:
            unreadable.append(path.name)
            continue
        docs.append(analyse(parse_file(path), target, reading, policy))

    return Report(
        target=target,
        reading=reading,
        policy=policy,
        docs=tuple(docs),
        unreadable=tuple(unreadable),
    )


def compare_targets(
    directory: Path,
    reading: Reading = Reading.PROMOTE,
    policy: FlattenPolicy = FlattenPolicy.DUPLICATE,
) -> dict[str, Report]:
    """Every target over the same corpus.

    The comparison is the argument: the parsers, the tree and the policy are identical
    across all four, so the differences are the formats'.
    """
    return {
        name: build_report(directory, name, reading, policy) for name in TARGETS
    }


def decode_survey(directory: Path) -> list[tuple[str, Decoding, int, bool]]:
    """(name, verdict, competing readings, recoverable) for every file's raw bytes.

    Run against bytes rather than parsed documents so a DOCX -- a ZIP container, and
    therefore never valid UTF-8 -- is excluded rather than reported as ambiguous text.
    """
    out: list[tuple[str, Decoding, int, bool]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() in (".docx",):
            continue
        result = decode_bytes(path.read_bytes())
        out.append((path.name, result.decoding, result.candidates, result.recoverable))
    return out


def fidelity_of(loss_list: tuple[FeatureLoss, ...], fidelity: Fidelity) -> int:
    return sum(loss.count for loss in loss_list if loss.fidelity is fidelity)
