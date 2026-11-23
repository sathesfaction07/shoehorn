"""Text rendering. Kept out of the CLI so the tables can be asserted directly in tests."""

from __future__ import annotations

from .formats import TARGETS, expressiveness
from .measure import Report
from .models import Expressiveness, Feature

SYMBOL = {
    Expressiveness.NATIVE: "yes",
    Expressiveness.APPROXIMATE: "approx",
    Expressiveness.ABSENT: "NO",
}


def matrix_table() -> str:
    """The capability matrix. The ceiling, in one table."""
    names = sorted(TARGETS)
    width = max(len(f.value) for f in Feature) + 2
    lines = [
        "  " + "feature".ljust(width) + "".join(n.rjust(10) for n in names),
        "  " + "-" * (width + 10 * len(names)),
    ]
    for feature in Feature:
        row = "  " + feature.value.ljust(width)
        for name in names:
            row += SYMBOL[expressiveness(name, feature)].rjust(10)
        lines.append(row)
    return "\n".join(lines)


def ceiling_table(report: Report) -> str:
    """What each target would lose on this corpus, from the census alone."""
    total = report.total_features
    lines = [
        f"  corpus contains {total} structural feature instances",
        "",
        f"  {'target':10}{'survives':>10}{'lost':>7}{'ceiling':>10}",
        "  " + "-" * 37,
    ]
    for name, (survives, lost) in sorted(
        report.ceiling_table.items(), key=lambda kv: kv[1][1]
    ):
        share = f"{survives / total:.1%}" if total else "n/a"
        lines.append(f"  {name:10}{survives:>10}{lost:>7}{share:>10}")
    return "\n".join(lines)


def loss_table(report: Report) -> str:
    """Per-document losses for the chosen target."""
    lines = [
        f"  {'document':26}{'fmt':>9}{'feat':>6}{'lost':>6}{'content':>9}"
        f"{'values':>9}  silent",
        "  " + "-" * 74,
    ]
    for doc in sorted(report.docs, key=lambda d: (-d.lost_instances, d.doc_id)):
        total = sum(doc.features.values())
        values = f"{doc.values_before}->{doc.values_after}"
        lines.append(
            f"  {doc.doc_id:26}{doc.source_format:>9}{total:>6}"
            f"{doc.lost_instances:>6}{doc.content_changed:>9}{values:>9}"
            f"  {'YES' if doc.is_silent else ''}"
        )
    return "\n".join(lines)


def feature_breakdown(report: Report) -> str:
    """Which features the chosen target lost, and how."""
    rows: dict[tuple[str, str], int] = {}
    for doc in report.docs:
        for loss in doc.losses:
            key = (loss.feature.value, loss.fidelity.value)
            rows[key] = rows.get(key, 0) + loss.count

    if not rows:
        return "  nothing lost"

    lines = [
        f"  {'feature':16}{'fidelity':>12}{'count':>8}",
        "  " + "-" * 36,
    ]
    for (feature, fidelity), count in sorted(rows.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {feature:16}{fidelity:>12}{count:>8}")
    return "\n".join(lines)
