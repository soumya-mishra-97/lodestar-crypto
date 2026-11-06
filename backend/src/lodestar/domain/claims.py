"""Claims: the only unit of prose a report may contain.

Every sentence carries a tag so the reader can see what kind of statement it is,
and the ids of the evidence it relies on so the verifier can check it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ClaimTag(StrEnum):
    FACT = "fact"  # restates an observation from a named provider
    CALCULATION = "calculation"  # restates a value computed by Lodestar code
    INTERPRETATION = "interpretation"  # reasoning over cited evidence
    SCENARIO = "scenario"  # conditional "if ... then ..." outcome, never a forecast
    ASSUMPTION = "assumption"  # a premise or limitation the analysis depends on


@dataclass(frozen=True, slots=True)
class Claim:
    text: str
    tag: ClaimTag
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "tag": self.tag.value, "evidence_ids": list(self.evidence_ids)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Claim:
        return cls(
            text=str(d["text"]).strip(),
            tag=ClaimTag(d["tag"]),
            evidence_ids=tuple(dict.fromkeys(str(i) for i in d.get("evidence_ids") or ())),
        )
