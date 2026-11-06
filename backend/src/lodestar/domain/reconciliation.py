"""Cross-provider reconciliation: never trust a single price feed silently.

Each source is compared with the median of all sources. Any deviation beyond the
tolerance is flagged as a mismatch; the flag becomes evidence, a risk factor and
a visible warning in the report.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ReconciliationStatus = Literal["consistent", "mismatch", "single_source"]


@dataclass(frozen=True, slots=True)
class SourcePrice:
    source: str
    price_usd: float
    as_of: datetime


@dataclass(frozen=True, slots=True)
class Comparison:
    source: str
    value: float
    deviation_pct: float
    within_tolerance: bool


@dataclass(frozen=True, slots=True)
class Reconciliation:
    field: str
    reference_value: float  # median across sources
    tolerance_pct: float
    comparisons: tuple[Comparison, ...]
    status: ReconciliationStatus

    @property
    def max_deviation_pct(self) -> float:
        return max((abs(c.deviation_pct) for c in self.comparisons), default=0.0)

    @property
    def mismatched_sources(self) -> list[str]:
        return [c.source for c in self.comparisons if not c.within_tolerance]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "reference_value": self.reference_value,
            "tolerance_pct": self.tolerance_pct,
            "status": self.status,
            "max_deviation_pct": round(self.max_deviation_pct, 4),
            "comparisons": [
                {
                    "source": c.source,
                    "value": c.value,
                    "deviation_pct": round(c.deviation_pct, 4),
                    "within_tolerance": c.within_tolerance,
                }
                for c in self.comparisons
            ],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Reconciliation:
        return cls(
            field=d["field"],
            reference_value=float(d["reference_value"]),
            tolerance_pct=float(d["tolerance_pct"]),
            comparisons=tuple(
                Comparison(c["source"], float(c["value"]), float(c["deviation_pct"]), bool(c["within_tolerance"]))
                for c in d["comparisons"]
            ),
            status=d["status"],
        )


def reconcile_prices(quotes: Sequence[SourcePrice], *, tolerance_pct: float) -> Reconciliation:
    usable = [q for q in quotes if q.price_usd > 0]
    if not usable:
        raise ValueError("at least one positive price is required")
    reference = statistics.median(q.price_usd for q in usable)
    comparisons = tuple(
        Comparison(
            source=q.source,
            value=q.price_usd,
            deviation_pct=(q.price_usd / reference - 1) * 100,
            within_tolerance=abs(q.price_usd / reference - 1) * 100 <= tolerance_pct,
        )
        for q in usable
    )
    if len(usable) == 1:
        status: ReconciliationStatus = "single_source"
    elif all(c.within_tolerance for c in comparisons):
        status = "consistent"
    else:
        status = "mismatch"
    return Reconciliation("price_usd", reference, tolerance_pct, comparisons, status)
