"""The report draft the writer produces and the verifier checks."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from lodestar.domain.claims import Claim

DISCLAIMER = (
    "Lodestar is a read-only research tool, not financial advice. Scores and risk levels are rule-based "
    "summaries of historical and current data; they are not predictions, guarantees or price targets. "
    "Crypto assets are highly volatile and you can lose some or all of the money you invest. "
    "Verify independently and consider your own circumstances before making any decision."
)


@dataclass(frozen=True, slots=True)
class HorizonNarrative:
    thesis: tuple[Claim, ...] = ()
    opportunities: tuple[Claim, ...] = ()
    risks: tuple[Claim, ...] = ()
    watch: tuple[Claim, ...] = ()

    SECTIONS = ("thesis", "opportunities", "risks", "watch")

    def sections(self) -> Iterator[tuple[str, tuple[Claim, ...]]]:
        for name in self.SECTIONS:
            yield name, getattr(self, name)

    def all(self) -> tuple[Claim, ...]:
        return self.thesis + self.opportunities + self.risks + self.watch

    def to_dict(self) -> dict[str, Any]:
        return {name: [c.to_dict() for c in claims] for name, claims in self.sections()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> HorizonNarrative:
        return cls(**{name: tuple(Claim.from_dict(c) for c in d.get(name) or ()) for name in cls.SECTIONS})


@dataclass(frozen=True, slots=True)
class ReportDraft:
    headline: Claim
    short_term: HorizonNarrative
    long_term: HorizonNarrative
    portfolio: tuple[Claim, ...] = ()
    data_quality: tuple[Claim, ...] = ()
    uncertainties: tuple[Claim, ...] = ()
    disclaimer: str = DISCLAIMER
    writer: str = "deterministic"  # "deterministic" or the model id

    LIST_SECTIONS = ("portfolio", "data_quality", "uncertainties")

    def located_claims(self) -> Iterator[tuple[str, Claim]]:
        """Every claim with a stable location label, e.g. ``short_term.risks[1]``."""
        yield "headline", self.headline
        for horizon in ("short_term", "long_term"):
            narrative: HorizonNarrative = getattr(self, horizon)
            for section, claims in narrative.sections():
                for i, claim in enumerate(claims):
                    yield f"{horizon}.{section}[{i}]", claim
        for section in self.LIST_SECTIONS:
            for i, claim in enumerate(getattr(self, section)):
                yield f"{section}[{i}]", claim

    def all_claims(self) -> list[Claim]:
        return [c for _, c in self.located_claims()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline.to_dict(),
            "short_term": self.short_term.to_dict(),
            "long_term": self.long_term.to_dict(),
            **{s: [c.to_dict() for c in getattr(self, s)] for s in self.LIST_SECTIONS},
            "disclaimer": self.disclaimer,
            "writer": self.writer,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ReportDraft:
        return cls(
            headline=Claim.from_dict(d["headline"]),
            short_term=HorizonNarrative.from_dict(d["short_term"]),
            long_term=HorizonNarrative.from_dict(d["long_term"]),
            **{s: tuple(Claim.from_dict(c) for c in d.get(s) or ()) for s in cls.LIST_SECTIONS},
            disclaimer=d.get("disclaimer", ""),
            writer=d.get("writer", "deterministic"),
        )
