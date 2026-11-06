"""Polymarket crowd odds (public Gamma API, read-only) as optional sentiment evidence.

Questions are untrusted third-party text; the pipeline sanitises them and they
are only ever cited as sentiment, never as a forecast or a price target.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from lodestar.domain.models import PredictionMarket
from lodestar.infrastructure.http import ResilientHttp

GAMMA = "https://gamma-api.polymarket.com/markets"
CACHE_SECONDS = 600


def _yes_pct(market: dict[str, Any]) -> float | None:
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices = json.loads(market.get("outcomePrices") or "[]")
        for name, price in zip(outcomes, prices, strict=False):
            if str(name).lower() == "yes":
                return float(price) * 100
    except (ValueError, TypeError):
        return None
    return None


class PolymarketProvider:
    def __init__(self, http: ResilientHttp, *, scan_limit: int = 500) -> None:
        self._http, self._scan_limit = http, scan_limit
        self._cached: tuple[float, list[dict[str, Any]]] | None = None

    async def _markets(self) -> list[dict[str, Any]]:
        if self._cached and time.monotonic() - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        data = await self._http.get_json(
            GAMMA,
            params={
                "active": "true",
                "closed": "false",
                "limit": self._scan_limit,
                "order": "volumeNum",
                "ascending": "false",
            },
        )
        markets = [m for m in data if isinstance(m, dict)] if isinstance(data, list) else []
        self._cached = (time.monotonic(), markets)
        return markets

    async def markets_for(self, *, name: str, symbol: str, limit: int) -> list[PredictionMarket]:
        terms = {t for t in (name.split(" (", maxsplit=1)[0].strip(), symbol) if len(t) >= 3}
        if not terms:
            return []
        pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.IGNORECASE)
        out = []
        for m in await self._markets():
            question = str(m.get("question") or "")
            yes = _yes_pct(m)
            if yes is None or not pattern.search(question):
                continue
            out.append(
                PredictionMarket(
                    id=str(m.get("id")),
                    question=question,
                    yes_probability_pct=round(yes, 2),
                    volume_usd=float(m["volumeNum"]) if isinstance(m.get("volumeNum"), int | float) else None,
                    end_date=m.get("endDate"),
                    url=f"https://polymarket.com/market/{m.get('slug', '')}",
                )
            )
            if len(out) >= limit:
                break
        return out
