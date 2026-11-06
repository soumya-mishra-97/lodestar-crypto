"""JSON <-> domain decoding for values that cross process boundaries.

Graph state (checkpointed by LangGraph) and cache entries hold plain JSON only,
never pickles: a poisoned entry must not be able to execute code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from lodestar.application.serialization import to_json_dict
from lodestar.domain.models import (
    Asset,
    AssetCandidate,
    Candle,
    ChainFees,
    ExchangeQuote,
    Fundamentals,
    FundingSnapshot,
    LiquidityProfile,
    MarketDataBundle,
    MarketHistory,
    MarketSnapshot,
    NewsItem,
    OrderBook,
    PredictionMarket,
    PricePoint,
    PriceQuote,
    SentimentSnapshot,
    TvlSnapshot,
)

J = Mapping[str, Any]


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _req_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def asset(d: J) -> Asset:
    return Asset(id=UUID(str(d["id"])), coingecko_id=d["coingecko_id"], symbol=d["symbol"], name=d["name"])


def candidate(d: J) -> AssetCandidate:
    return AssetCandidate(**d)


def snapshot(d: J) -> MarketSnapshot:
    return MarketSnapshot(**{**d, "as_of": _req_dt(d["as_of"])})


def history(d: J) -> MarketHistory:
    return MarketHistory(
        coingecko_id=d["coingecko_id"],
        points=tuple(PricePoint(**{**p, "ts": _req_dt(p["ts"])}) for p in d["points"]),
    )


def candle(d: J) -> Candle:
    return Candle(**{**d, "ts": _req_dt(d["ts"])})


def exchange_quote(d: J) -> ExchangeQuote:
    return ExchangeQuote(**{**d, "as_of": _req_dt(d["as_of"])})


def price_quote(d: J) -> PriceQuote:
    return PriceQuote(**{**d, "as_of": _req_dt(d["as_of"])})


def fundamentals(d: J) -> Fundamentals:
    return Fundamentals(**{**d, "categories": tuple(d.get("categories") or ())})


def liquidity(d: J) -> LiquidityProfile:
    return LiquidityProfile(**d)


def sentiment(d: J) -> SentimentSnapshot:
    return SentimentSnapshot(**{**d, "as_of": _req_dt(d["as_of"])})


def tvl(d: J) -> TvlSnapshot:
    return TvlSnapshot(**{**d, "as_of": _req_dt(d["as_of"])})


def news_item(d: J) -> NewsItem:
    return NewsItem(**{**d, "published_at": _dt(d.get("published_at"))})


def prediction_market(d: J) -> PredictionMarket:
    return PredictionMarket(**d)


def order_book(d: J) -> OrderBook:
    return OrderBook(
        venue=d["venue"],
        pair=d["pair"],
        bids=tuple((float(p), float(q)) for p, q in d["bids"]),
        asks=tuple((float(p), float(q)) for p, q in d["asks"]),
        as_of=_req_dt(d["as_of"]),
    )


def funding(d: J) -> FundingSnapshot:
    return FundingSnapshot(**{**d, "as_of": _req_dt(d["as_of"])})


def chain_fees(d: J) -> ChainFees:
    return ChainFees(**{**d, "as_of": _req_dt(d["as_of"])})


def encode_bundle(bundle: MarketDataBundle) -> dict[str, Any]:
    return to_json_dict(bundle)


def decode_bundle(d: J) -> MarketDataBundle:
    def opt(key: str, fn: Any) -> Any:
        return fn(d[key]) if d.get(key) is not None else None

    return MarketDataBundle(
        snapshot=snapshot(d["snapshot"]),
        history=history(d["history"]),
        candles=tuple(candle(c) for c in d.get("candles") or ()),
        exchange=opt("exchange", exchange_quote),
        reference_price=opt("reference_price", price_quote),
        fundamentals=opt("fundamentals", fundamentals),
        liquidity=opt("liquidity", liquidity),
        sentiment=opt("sentiment", sentiment),
        tvl=opt("tvl", tvl),
        news=tuple(news_item(n) for n in d.get("news") or ()),
        prediction_markets=tuple(prediction_market(p) for p in d.get("prediction_markets") or ()),
        order_book=opt("order_book", order_book),
        funding=opt("funding", funding),
        chain_fees=opt("chain_fees", chain_fees),
        data_gaps=list(d.get("data_gaps") or ()),
    )
