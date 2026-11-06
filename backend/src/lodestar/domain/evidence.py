"""Evidence: the closed world of values a report may cite.

Every value an agent or the report writer may mention is registered here first,
by code, with a stable id (``DAT-01``, ``TEC-04``, ``NWS-2``...). The prefix names
the pipeline step that produced it, so ids from parallel agents never collide.

Three kinds:
  observation   a value read from a named provider (CoinGecko, Kraken, ...)
  calculation   a value computed by Lodestar code, with the ids it was derived from
  text          untrusted third-party text (headlines, market questions): context only
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

Unit = Literal["usd", "pct", "ratio", "index", "count", "days", "text"]


class EvidenceKind(StrEnum):
    OBSERVATION = "observation"
    CALCULATION = "calculation"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    key: str
    label: str
    value: float | str
    unit: Unit
    kind: EvidenceKind
    source: str
    as_of: str
    inputs: tuple[str, ...] = ()  # lineage: ids a calculation was derived from

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.value, int | float)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "kind": self.kind.value,
            "source": self.source,
            "as_of": self.as_of,
            "inputs": list(self.inputs),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Evidence:
        return cls(
            id=d["id"],
            key=d["key"],
            label=d["label"],
            value=d["value"],
            unit=d["unit"],
            kind=EvidenceKind(d["kind"]),
            source=d["source"],
            as_of=d["as_of"],
            inputs=tuple(d.get("inputs") or ()),
        )


def _round(value: float) -> float:
    return round(value, 8 if abs(value) < 1 else 4)


class EvidenceRegistry:
    """Append-only evidence store for one producer (one id namespace).

    Registering the same key twice with the same value returns the existing id,
    so an agent that repeats a tool call does not inflate the bundle.
    """

    def __init__(self, namespace: str, *, as_of: datetime, width: int = 2) -> None:
        self._ns, self._as_of, self._width = namespace, as_of, width
        self._items: list[Evidence] = []
        self._by_key: dict[str, Evidence] = {}

    @property
    def namespace(self) -> str:
        return self._ns

    def _add(
        self,
        key: str,
        label: str,
        value: float | str | None,
        unit: Unit,
        kind: EvidenceKind,
        source: str,
        as_of: datetime | None,
        inputs: Iterable[str],
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, float | int) and not isinstance(value, bool):
            value = _round(float(value))
        existing = self._by_key.get(key)
        if existing is not None and existing.value == value:
            return existing.id
        item = Evidence(
            id=f"{self._ns}-{len(self._items) + 1:0{self._width}d}",
            key=key,
            label=label,
            value=value,
            unit=unit,
            kind=kind,
            source=source,
            as_of=(as_of or self._as_of).isoformat(),
            inputs=tuple(dict.fromkeys(i for i in inputs if i)),
        )
        self._items.append(item)
        self._by_key[key] = item
        return item.id

    def observe(
        self,
        key: str,
        label: str,
        value: float | str | None,
        unit: Unit,
        *,
        source: str,
        as_of: datetime | None = None,
    ) -> str | None:
        return self._add(key, label, value, unit, EvidenceKind.OBSERVATION, source, as_of, ())

    def calculate(
        self,
        key: str,
        label: str,
        value: float | str | None,
        unit: Unit,
        *,
        inputs: Iterable[str | None] = (),
        source: str = "lodestar",
    ) -> str | None:
        return self._add(key, label, value, unit, EvidenceKind.CALCULATION, source, None, (i for i in inputs if i))

    def text(self, key: str, label: str, value: str, *, source: str, as_of: datetime | None = None) -> str | None:
        return self._add(key, label, value, "text", EvidenceKind.TEXT, source, as_of, ())

    def get_by_key(self, key: str) -> Evidence | None:
        return self._by_key.get(key)

    def id_of(self, key: str) -> str | None:
        item = self._by_key.get(key)
        return item.id if item else None

    @property
    def items(self) -> tuple[Evidence, ...]:
        return tuple(self._items)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Read-only view over all evidence registered during a run."""

    items: tuple[Evidence, ...]

    @classmethod
    def from_dicts(cls, rows: Iterable[Mapping[str, Any]]) -> EvidenceBundle:
        seen: dict[str, Evidence] = {}
        for row in rows:
            seen.setdefault(row["id"], Evidence.from_dict(row))
        return cls(tuple(seen.values()))

    def ids(self) -> set[str]:
        return {e.id for e in self.items}

    def get(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.items if e.id == evidence_id), None)

    def by_key(self, key: str, *, namespace: str | None = None) -> Evidence | None:
        return next(
            (e for e in self.items if e.key == key and (namespace is None or e.id.startswith(f"{namespace}-"))),
            None,
        )

    def in_namespace(self, namespace: str) -> tuple[Evidence, ...]:
        return tuple(e for e in self.items if e.id.startswith(f"{namespace}-"))

    def to_dicts(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.items]
