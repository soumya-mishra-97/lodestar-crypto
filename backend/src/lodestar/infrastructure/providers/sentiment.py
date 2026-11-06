"""Market-wide sentiment from the alternative.me Crypto Fear & Greed Index (free, no key)."""

from __future__ import annotations

from datetime import UTC, datetime

from lodestar.domain.errors import ProviderUnavailable
from lodestar.domain.models import SentimentSnapshot
from lodestar.infrastructure.http import ResilientHttp

FNG_URL = "https://api.alternative.me/fng/"


class FearGreedProvider:
    def __init__(self, http: ResilientHttp) -> None:
        self._http = http

    async def get_market_sentiment(self) -> SentimentSnapshot:
        data = await self._http.get_json(FNG_URL, params={"limit": 1})
        try:
            row = data["data"][0]
            return SentimentSnapshot(
                fear_greed_value=int(row["value"]),
                classification=str(row["value_classification"])[:32],
                as_of=datetime.fromtimestamp(int(row["timestamp"]), tz=UTC),
            )
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderUnavailable("Unexpected Fear & Greed payload") from exc
