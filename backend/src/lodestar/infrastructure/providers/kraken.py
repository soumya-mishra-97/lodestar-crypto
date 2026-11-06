"""Kraken public market data (no key): daily OHLC candles and the live ticker.

Kraken is the exchange source for candles and the second price feed used to
reconcile CoinGecko. Pairs Kraken does not list return None/[] (not an error).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from lodestar.domain.errors import ProviderUnavailable
from lodestar.domain.models import Candle, ExchangeQuote, FundingSnapshot, OrderBook
from lodestar.infrastructure.http import ResilientHttp

BASE = "https://api.kraken.com/0/public"
# Kraken's own asset codes for a few well-known tickers.
SYMBOL_ALIASES = {"BTC": "XBT", "DOGE": "XDG"}
UNKNOWN_PAIR_TTL = 6 * 3600


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class KrakenProvider:
    venue = "kraken"

    def __init__(self, http: ResilientHttp) -> None:
        self._http = http
        self._unknown: dict[str, float] = {}  # pair -> when we learned Kraken doesn't list it

    @staticmethod
    def pair_for(symbol: str) -> str:
        return f"{SYMBOL_ALIASES.get(symbol.upper(), symbol.upper())}USD"

    async def _public(self, endpoint: str, pair: str, **params: Any) -> dict[str, Any] | None:
        seen = self._unknown.get(pair)
        if seen is not None and time.monotonic() - seen < UNKNOWN_PAIR_TTL:
            return None
        data = await self._http.get_json(f"{BASE}/{endpoint}", params={"pair": pair, **params})
        errors = data.get("error") or []
        if any("Unknown asset pair" in e for e in errors):
            self._unknown[pair] = time.monotonic()
            return None
        if errors:
            raise ProviderUnavailable(f"Kraken error: {errors[0][:80]}")
        result: dict[str, Any] = data.get("result") or {}
        # The result is keyed by Kraken's canonical pair name (e.g. XXBTZUSD); "last" is a cursor.
        return next((v for k, v in result.items() if k != "last"), None)

    async def get_quote(self, symbol: str) -> ExchangeQuote | None:
        pair = self.pair_for(symbol)
        row = await self._public("Ticker", pair)
        if not row:
            return None
        price = _f((row.get("c") or [None])[0])
        if price is None:
            return None
        return ExchangeQuote(
            venue=self.venue,
            pair=pair,
            price_usd=price,
            bid=_f((row.get("b") or [None])[0]),
            ask=_f((row.get("a") or [None])[0]),
            volume_24h_base=_f((row.get("v") or [None, None])[1]),
            as_of=datetime.now(UTC),
        )

    async def get_order_book(self, symbol: str) -> OrderBook | None:
        pair = self.pair_for(symbol)
        book = await self._public("Depth", pair, count=200)
        if not book:
            return None

        def levels(rows: list[list[Any]]) -> tuple[tuple[float, float], ...]:
            return tuple((p, q) for r in rows if (p := _f(r[0])) and (q := _f(r[1])))

        return OrderBook(
            self.venue, pair, levels(book.get("bids") or []), levels(book.get("asks") or []), datetime.now(UTC)
        )

    async def get_candles(self, symbol: str, days: int) -> list[Candle]:
        rows = await self._public("OHLC", self.pair_for(symbol), interval=1440)
        if not rows:
            return []
        candles = []
        for r in rows:
            o, h, low, c, v = (_f(x) for x in (r[1], r[2], r[3], r[4], r[6]))
            if None in (o, h, low, c, v):
                continue
            candles.append(Candle(datetime.fromtimestamp(int(r[0]), tz=UTC), o, h, low, c, v))  # type: ignore[arg-type]
        return candles[-days:]


FUTURES_TICKERS = "https://futures.kraken.com/derivatives/api/v3/tickers"
FUNDING_CACHE_SECONDS = 300


class KrakenFuturesFunding:
    """Perpetual funding from Kraken Futures' public tickers (no key).

    Kraken reports `fundingRate` in quote currency per contract per hour; dividing by the
    mark price gives the relative hourly rate.
    """

    venue = "kraken-futures"

    def __init__(self, http: ResilientHttp) -> None:
        self._http = http
        self._cached: tuple[float, list[dict[str, Any]]] | None = None

    async def _tickers(self) -> list[dict[str, Any]]:
        if self._cached and time.monotonic() - self._cached[0] < FUNDING_CACHE_SECONDS:
            return self._cached[1]
        data = await self._http.get_json(FUTURES_TICKERS)
        tickers = [t for t in (data.get("tickers") or []) if isinstance(t, dict)]
        self._cached = (time.monotonic(), tickers)
        return tickers

    async def get_funding(self, symbol: str) -> FundingSnapshot | None:
        wanted = f"PF_{SYMBOL_ALIASES.get(symbol.upper(), symbol.upper())}USD"
        row = next((t for t in await self._tickers() if t.get("symbol") == wanted), None)
        if not row:
            return None
        rate, mark = _f(row.get("fundingRate")), _f(row.get("markPrice"))
        if rate is None or not mark:
            return None
        return FundingSnapshot(self.venue, wanted, rate / mark * 100, datetime.now(UTC))
