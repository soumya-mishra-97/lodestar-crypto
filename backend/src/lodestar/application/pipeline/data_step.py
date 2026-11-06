"""The Data step: collect from every provider, sanitise, reconcile, register evidence.

Core data (snapshot + history) is required; everything else is optional and a
missing source becomes a recorded data gap, never an invented value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar, cast

import structlog

from lodestar.application.ports import DataSources
from lodestar.application.sanitize import clean_untrusted_text, looks_like_injection
from lodestar.domain.errors import InsufficientData, LodestarError
from lodestar.domain.evidence import Evidence, EvidenceRegistry
from lodestar.domain.models import Asset, Candle, MarketDataBundle, NewsItem, PredictionMarket
from lodestar.domain.reconciliation import Reconciliation, SourcePrice, reconcile_prices

log = structlog.get_logger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CollectionSettings:
    history_days: int = 365
    candle_days: int = 180
    min_history_days: int = 30
    source_timeout_seconds: float = 20.0
    max_headlines: int = 8
    max_prediction_markets: int = 5


class DataCollector:
    def __init__(self, sources: DataSources, settings: CollectionSettings) -> None:
        self._s, self._cfg = sources, settings

    async def collect(self, asset: Asset, *, polymarket_enabled: bool) -> MarketDataBundle:
        cg, cfg = asset.coingecko_id, self._cfg
        try:
            snapshot, history = await asyncio.gather(
                self._bounded(self._s.market.get_snapshot(cg)),
                self._bounded(self._s.market.get_history(cg, cfg.history_days)),
            )
        except (LodestarError, TimeoutError) as exc:
            raise InsufficientData(f"Core market data unavailable for {asset.symbol}: {exc}") from exc
        if len(history.points) < cfg.min_history_days:
            raise InsufficientData(f"Only {len(history.points)} days of history for {asset.symbol}")

        bundle = MarketDataBundle(snapshot=snapshot, history=history)

        async def none() -> None:
            return None

        optional = await asyncio.gather(
            self._bounded(self._s.exchange.get_candles(asset.symbol, cfg.candle_days)),
            self._bounded(self._s.exchange.get_quote(asset.symbol)),
            self._bounded(self._s.reference.get_price(cg)),
            self._bounded(self._s.market.get_fundamentals(cg)),
            self._bounded(self._s.market.get_liquidity(cg)),
            self._bounded(self._s.sentiment.get_market_sentiment()),
            self._bounded(self._s.onchain.get_chain_tvl(cg)),
            self._bounded(self._s.news.latest(name=asset.name, symbol=asset.symbol, limit=cfg.max_headlines * 2)),
            self._bounded(
                self._s.predictions.markets_for(name=asset.name, symbol=asset.symbol, limit=cfg.max_prediction_markets)
                if polymarket_enabled
                else none()
            ),
            self._bounded(self._s.exchange.get_order_book(asset.symbol)),
            self._bounded(self._s.derivatives.get_funding(asset.symbol)),
            self._bounded(self._s.fees.get_chain_fees(cg)),
            return_exceptions=True,
        )
        names = (
            "candles",
            "exchange",
            "reference_price",
            "fundamentals",
            "liquidity",
            "sentiment",
            "tvl",
            "news",
            "prediction_markets",
            "order_book",
            "funding",
            "chain_fees",
        )
        for name, value in zip(names, optional, strict=True):
            if isinstance(value, BaseException):
                if not isinstance(value, Exception):
                    raise value
                log.warning("source_unavailable", source=name, asset=cg, error=repr(value))
                bundle.data_gaps.append(f"{name.replace('_', ' ')} unavailable")
                continue
            if name == "candles":
                bundle.candles = tuple(cast(list[Candle], value))
                if not value:
                    bundle.data_gaps.append(f"no {self._s.exchange.venue} market for {asset.symbol}/USD")
            elif name == "news":
                bundle.news = self._screen_news(cast(list[NewsItem], value), bundle)
            elif name == "prediction_markets":
                bundle.prediction_markets = self._screen_markets(cast(list[PredictionMarket], value or []), bundle)
            elif value is not None:
                setattr(bundle, name, value)
        if bundle.liquidity is not None and bundle.liquidity.depth_2pct_usd is None:
            bundle.data_gaps.append("order-book depth not provided by the market data plan")
        return bundle

    def _screen_news(self, items: list[NewsItem], bundle: MarketDataBundle) -> tuple[NewsItem, ...]:
        kept, dropped = [], 0
        for item in items:
            title = clean_untrusted_text(item.title)
            if not title or looks_like_injection(title):
                dropped += 1
                continue
            kept.append(NewsItem(title, clean_untrusted_text(item.source, 60), item.url, item.published_at))
        if dropped:
            bundle.data_gaps.append(f"{dropped} headline(s) discarded by the content filter")
        return tuple(kept[: self._cfg.max_headlines])

    def _screen_markets(self, items: list[PredictionMarket], bundle: MarketDataBundle) -> tuple[PredictionMarket, ...]:
        kept = []
        for m in items:
            question = clean_untrusted_text(m.question, 200)
            if question and not looks_like_injection(question) and 0 <= m.yes_probability_pct <= 100:
                kept.append(PredictionMarket(m.id, question, m.yes_probability_pct, m.volume_usd, m.end_date, m.url))
        if len(kept) < len(items):
            bundle.data_gaps.append(f"{len(items) - len(kept)} prediction market(s) discarded by the content filter")
        return tuple(kept)

    async def _bounded(self, aw: Awaitable[T]) -> T:
        return await asyncio.wait_for(aw, timeout=self._cfg.source_timeout_seconds)


def reconcile(bundle: MarketDataBundle, *, tolerance_pct: float, primary_source: str) -> Reconciliation:
    quotes = [SourcePrice(primary_source, bundle.snapshot.price_usd, bundle.snapshot.as_of)]
    if bundle.exchange is not None:
        quotes.append(SourcePrice(bundle.exchange.venue, bundle.exchange.price_usd, bundle.exchange.as_of))
    if bundle.reference_price is not None:
        rp = bundle.reference_price
        quotes.append(SourcePrice(rp.source, rp.price_usd, rp.as_of))
    return reconcile_prices(quotes, tolerance_pct=tolerance_pct)


def register_data_evidence(
    bundle: MarketDataBundle,
    reconciliation: Reconciliation,
    *,
    primary_source: str,
    now: datetime,
) -> list[Evidence]:
    """Turn the collected bundle into citable evidence (DAT-, NWS-, PM- namespaces)."""
    d = EvidenceRegistry("DAT", as_of=now)
    s, t, src = bundle.snapshot, bundle.snapshot.as_of, primary_source

    d.observe("price_usd", "Current price (USD)", s.price_usd, "usd", source=src, as_of=t)
    last = bundle.history.points[-1]
    d.observe("last_close", "Latest daily close (USD)", last.price, "usd", source=src, as_of=last.ts)
    d.observe("market_cap_usd", "Market capitalisation (USD)", s.market_cap_usd, "usd", source=src, as_of=t)
    d.observe("fdv_usd", "Fully diluted valuation (USD)", s.fdv_usd, "usd", source=src, as_of=t)
    d.observe("volume_24h_usd", "24h trading volume (USD)", s.volume_24h_usd, "usd", source=src, as_of=t)
    rank = float(s.market_cap_rank) if s.market_cap_rank else None
    d.observe("market_cap_rank", "Market cap rank", rank, "count", source=src, as_of=t)
    d.observe("change_24h_pct", "24h price change (%)", s.change_24h_pct, "pct", source=src, as_of=t)
    d.observe("change_7d_pct", "7-day price change (%)", s.change_7d_pct, "pct", source=src, as_of=t)
    d.observe("change_30d_pct", "30-day price change (%)", s.change_30d_pct, "pct", source=src, as_of=t)
    d.observe("change_1y_pct", "1-year price change (%)", s.change_1y_pct, "pct", source=src, as_of=t)
    d.observe("ath_usd", "All-time high (USD)", s.ath_usd, "usd", source=src, as_of=t)
    d.observe("ath_change_pct", "Distance from all-time high (%)", s.ath_change_pct, "pct", source=src, as_of=t)
    d.calculate(
        "history_days", "Days of daily price history analysed", float(len(bundle.history.points)), "days", inputs=()
    )

    if f := bundle.fundamentals:
        d.observe(
            "circulating_supply", "Circulating supply (tokens)", f.circulating_supply, "count", source=src, as_of=t
        )
        d.observe("total_supply", "Total supply (tokens)", f.total_supply, "count", source=src, as_of=t)
        d.observe(
            "max_supply",
            "Max supply (tokens)",
            f.max_supply if f.max_supply else "uncapped",
            "count",
            source=src,
            as_of=t,
        )
    if liq := bundle.liquidity:
        d.observe(
            "depth_2pct_usd", "Order-book depth within ±2% (USD, top venues)", liq.depth_2pct_usd, "usd", source=src
        )
        d.observe("median_spread_pct", "Median bid-ask spread (%)", liq.median_spread_pct, "pct", source=src)
        d.observe(
            "top_venue_share_pct",
            "Largest venue's share of volume (%)",
            liq.top_venue_volume_share_pct,
            "pct",
            source=src,
        )
        d.observe("venue_count", "Trusted venues analysed", float(liq.venue_count), "count", source=src)
    if ex := bundle.exchange:
        d.observe(
            "exchange_price_usd",
            f"{ex.venue} last price ({ex.pair})",
            ex.price_usd,
            "usd",
            source=ex.venue,
            as_of=ex.as_of,
        )
        d.observe(
            "exchange_spread_pct",
            f"{ex.venue} bid-ask spread (%)",
            ex.spread_pct,
            "pct",
            source=ex.venue,
            as_of=ex.as_of,
        )
        d.observe(
            "exchange_volume_24h",
            f"{ex.venue} 24h volume (base units)",
            ex.volume_24h_base,
            "count",
            source=ex.venue,
            as_of=ex.as_of,
        )
    if rp := bundle.reference_price:
        d.observe(
            "reference_price_usd",
            f"{rp.source} aggregated price (USD)",
            rp.price_usd,
            "usd",
            source=rp.source,
            as_of=rp.as_of,
        )
    if sen := bundle.sentiment:
        d.observe(
            "fear_greed",
            "Crypto Fear & Greed Index (0-100)",
            float(sen.fear_greed_value),
            "index",
            source="alternative.me",
            as_of=sen.as_of,
        )
        d.observe(
            "fear_greed_label",
            "Fear & Greed classification",
            sen.classification,
            "text",
            source="alternative.me",
            as_of=sen.as_of,
        )
    if tvl := bundle.tvl:
        d.observe(
            "tvl_usd", f"{tvl.chain} total value locked (USD)", tvl.tvl_usd, "usd", source="defillama", as_of=tvl.as_of
        )
        d.observe(
            "tvl_change_30d_pct",
            f"{tvl.chain} TVL 30-day change (%)",
            tvl.change_30d_pct,
            "pct",
            source="defillama",
            as_of=tvl.as_of,
        )

    if book := bundle.order_book:
        d.observe(
            "book_spread_pct",
            f"{book.venue} order-book spread (%)",
            book.spread_pct,
            "pct",
            source=book.venue,
            as_of=book.as_of,
        )
        d.calculate(
            "book_depth_2pct_usd", f"{book.venue} order-book depth within ±2% (USD)", book.depth_usd(2.0), "usd"
        )
    if fr := bundle.funding:
        d.observe(
            "funding_rate_hourly_pct",
            f"Perpetual funding rate ({fr.symbol}, % per hour)",
            fr.rate_hourly_pct,
            "pct",
            source=fr.venue,
            as_of=fr.as_of,
        )
        d.calculate(
            "funding_rate_annual_pct",
            "Funding rate annualised (%)",
            fr.annualized_pct,
            "pct",
            inputs=[d.id_of("funding_rate_hourly_pct")],
        )
    if cf := bundle.chain_fees:
        d.observe(
            "chain_fees_30d_usd",
            f"{cf.chain} fees, last 30 days (USD)",
            cf.fees_30d_usd,
            "usd",
            source="defillama",
            as_of=cf.as_of,
        )
        d.observe(
            "chain_revenue_30d_usd",
            f"{cf.chain} revenue, last 30 days (USD)",
            cf.revenue_30d_usd,
            "usd",
            source="defillama",
            as_of=cf.as_of,
        )

    price_ids = [d.id_of(k) for k in ("price_usd", "exchange_price_usd", "reference_price_usd")]
    d.calculate(
        "price_reconciliation", "Price agreement across sources", reconciliation.status, "text", inputs=price_ids
    )
    d.calculate(
        "price_max_deviation_pct",
        f"Largest price deviation from the cross-source median (tolerance {reconciliation.tolerance_pct:g}%)",
        reconciliation.max_deviation_pct,
        "pct",
        inputs=price_ids,
    )
    d.calculate(
        "price_source_count",
        "Independent price sources compared",
        float(len(reconciliation.comparisons)),
        "count",
        inputs=price_ids,
    )

    news = EvidenceRegistry("NWS", as_of=now, width=1)
    for i, item in enumerate(bundle.news, start=1):
        news.text(f"headline_{i}", f"Headline · {item.source}", item.title, source=item.source, as_of=item.published_at)
    markets = EvidenceRegistry("PM", as_of=now, width=1)
    for i, m in enumerate(bundle.prediction_markets, start=1):
        markets.observe(
            f"market_{i}_yes_pct",
            f"Polymarket: {m.question} (yes %)",
            m.yes_probability_pct,
            "pct",
            source="polymarket",
        )
    return [*d.items, *news.items, *markets.items]


def collection_summary(bundle: MarketDataBundle, reconciliation: Reconciliation) -> dict[str, Any]:
    return {
        "price_usd": bundle.snapshot.price_usd,
        "history_days": len(bundle.history.points),
        "candles": len(bundle.candles),
        "exchange": bundle.exchange.venue if bundle.exchange else None,
        "headlines": len(bundle.news),
        "prediction_markets": len(bundle.prediction_markets),
        "reconciliation": reconciliation.to_dict(),
        "data_gaps": bundle.data_gaps,
    }
