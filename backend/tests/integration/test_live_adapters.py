"""Live-data adapters against recorded payload shapes (httpx.MockTransport): no network."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from lodestar.domain.addresses import Chain
from lodestar.domain.errors import NotFoundError, ProviderUnavailable
from lodestar.infrastructure.http import ResilientHttp
from lodestar.infrastructure.providers.coingecko import CoinGeckoProvider
from lodestar.infrastructure.providers.defillama import DefiLlamaPriceProvider
from lodestar.infrastructure.providers.kraken import KrakenProvider
from lodestar.infrastructure.providers.news import RssNewsProvider
from lodestar.infrastructure.providers.polymarket import PolymarketProvider
from lodestar.infrastructure.providers.wallets import PublicChainBalances

Handler = Callable[[httpx.Request], httpx.Response]


def http(handler: Handler, **kw: Any) -> ResilientHttp:
    return ResilientHttp(transport=httpx.MockTransport(handler), backoff_seconds=0.0, **kw)


def ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


async def test_kraken_ticker_candles_and_unlisted_pairs() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.params["pair"])
        if req.url.params["pair"] == "NOPEUSD":
            return ok({"error": ["EQuery:Unknown asset pair"]})
        if req.url.path.endswith("/Ticker"):
            row = {
                "a": ["0.0878", "1", "1"],
                "b": ["0.0877", "1", "1"],
                "c": ["0.08775", "5"],
                "v": ["10", "2336419.6"],
            }
            return ok({"error": [], "result": {"XXBTZUSD" if "XBT" in req.url.params["pair"] else "POLUSD": row}})
        rows = [[1731456000 + i * 86400, "1", "2", "0.5", str(1 + i), "1.1", "1000", 5] for i in range(5)]
        return ok({"error": [], "result": {"POLUSD": rows, "last": 1731801600}})

    kraken = KrakenProvider(http(handler))
    quote = await kraken.get_quote("POL")
    assert quote is not None
    assert (quote.price_usd, quote.bid, quote.ask, quote.volume_24h_base) == (0.08775, 0.0877, 0.0878, 2336419.6)
    assert quote.spread_pct == pytest.approx(0.1139, abs=1e-3)
    assert await kraken.get_quote("BTC") is not None
    assert calls[-1] == "XBTUSD"  # Kraken's code for bitcoin
    candles = await kraken.get_candles("POL", 3)
    assert [c.close for c in candles] == [3.0, 4.0, 5.0]
    assert await kraken.get_quote("NOPE") is None
    assert await kraken.get_candles("NOPE", 10) == []
    assert calls.count("NOPEUSD") == 1  # unknown pairs are remembered, not re-queried


async def test_defillama_reference_price() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "polygon" in req.url.path:
            return ok({"coins": {"coingecko:polygon-ecosystem-token": {"price": 0.0876, "timestamp": 1793705780}}})
        return ok({"coins": {}})

    llama = DefiLlamaPriceProvider(http(handler))
    quote = await llama.get_price("polygon-ecosystem-token")
    assert quote is not None
    assert (quote.source, quote.price_usd) == ("defillama", 0.0876)
    assert await llama.get_price("unknown") is None


async def test_polymarket_filters_by_asset_and_parses_yes_odds() -> None:
    markets = [
        {
            "id": "1",
            "question": "Will Bitcoin reach a new high in 2026?",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.62","0.38"]',
            "volumeNum": 1e6,
            "slug": "btc",
        },
        {
            "id": "2",
            "question": "Will it rain in Paris?",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.5","0.5"]',
            "slug": "rain",
        },
        {
            "id": "3",
            "question": "BTC dominance above 60%?",
            "outcomes": '["Up","Down"]',
            "outcomePrices": '["0.5","0.5"]',
        },
    ]
    seen: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(1)
        return ok(markets)

    pm = PolymarketProvider(http(handler))
    found = await pm.markets_for(name="Bitcoin", symbol="BTC", limit=5)
    assert [(m.id, m.yes_probability_pct) for m in found] == [("1", 62.0)]  # no "Yes" outcome -> skipped
    await pm.markets_for(name="Ethereum", symbol="ETH", limit=5)
    assert len(seen) == 1  # the market scan is cached


async def test_coingecko_snapshot_history_and_unknown_coin() -> None:
    coin = {
        "id": "polygon-ecosystem-token",
        "symbol": "pol",
        "name": "POL (ex-MATIC)",
        "market_cap_rank": 48,
        "market_data": {
            "current_price": {"usd": 0.0878},
            "market_cap": {"usd": 9.2e8},
            "total_volume": {"usd": 3.1e7},
            "price_change_percentage_24h": -2.1,
            "ath": {"usd": 2.9},
            "ath_change_percentage": {"usd": -96.9},
            "circulating_supply": 1.04e10,
            "total_supply": 1.05e10,
            "max_supply": None,
            "last_updated": "2026-11-03T11:00:00Z",
        },
    }

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/coins/nope"):
            return httpx.Response(404, json={"error": "coin not found"})
        if path.endswith("/market_chart"):
            day = 86_400_000
            prices = [[1_700_000_000_000 + i * day, 1.0 + i] for i in range(3)] + [
                [1_700_000_000_000 + 2 * day + 3600_000, 9.0]
            ]
            return ok({"prices": prices, "total_volumes": [[p[0], 100.0] for p in prices], "market_caps": []})
        assert req.headers["x-cg-demo-api-key"] == "k"
        return ok(coin)

    cg = CoinGeckoProvider(http(handler), api_key="k", plan="demo")
    snap = await cg.get_snapshot("polygon-ecosystem-token")
    assert (snap.price_usd, snap.market_cap_rank, snap.ath_change_pct) == (0.0878, 48, -96.9)
    f = await cg.get_fundamentals("polygon-ecosystem-token")
    assert f.max_supply is None
    assert f.circulating_supply == 1.04e10
    history = await cg.get_history("polygon-ecosystem-token", 3)
    assert history.closes == [1.0, 2.0, 9.0]  # one point per day, the latest wins
    with pytest.raises(NotFoundError):
        await cg.get_profile("nope")


async def test_public_wallet_balances_read_only() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "mempool.space":
            return ok(
                {"chain_stats": {"funded_txo_sum": 150_000_000, "spent_txo_sum": 50_000_000}, "mempool_stats": {}}
            )
        body = json.loads(req.content)
        bodies.append(body)
        if body["method"] == "eth_getBalance":
            return ok({"jsonrpc": "2.0", "id": 1, "result": hex(2 * 10**18)})
        to = body["params"][0]["to"]
        amount = 1500 * 10**18 if to.startswith("0x455e") else 0  # only POL is held
        return ok({"jsonrpc": "2.0", "id": 1, "result": hex(amount)})

    wallets = PublicChainBalances(http(handler), {"ethereum": "https://rpc.example", "polygon": "https://rpc2.example"})
    address = "0x" + "ab" * 20
    eth = await wallets.balances(Chain.ETHEREUM, address)
    assert [(b.symbol, b.quantity) for b in eth] == [("ETH", 2.0), ("POL", 1500.0)]
    assert {b["method"] for b in bodies} == {"eth_getBalance", "eth_call"}  # reads only, never a send
    assert all(b["params"][0]["data"].endswith("ab" * 20) for b in bodies if b["method"] == "eth_call")
    btc = await wallets.balances(Chain.BITCOIN, "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
    assert [(b.symbol, b.quantity) for b in btc] == [("BTC", 1.0)]


async def test_rss_news_filters_to_the_asset() -> None:
    rss = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Polygon ships a major upgrade</title><link>https://news.example/a</link>
          <pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>Unrelated macro story</title><link>https://news.example/b</link></item>
      <item><title>MATIC holders migrate to POL</title><link>http://insecure.example/c</link></item>
    </channel></rss>"""
    news = RssNewsProvider(http(lambda req: httpx.Response(200, content=rss)), ["https://news.example/feed"])
    items = await news.latest(name="POL (ex-MATIC)", symbol="POL", limit=5)
    assert [i.title for i in items] == ["Polygon ships a major upgrade"]  # https links only, relevant only


async def test_retries_then_opens_the_circuit() -> None:
    attempts: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503)

    client = http(handler, max_retries=1)
    for _ in range(5):
        with pytest.raises(ProviderUnavailable):
            await client.get_json("https://flaky.example/x")
    assert len(attempts) == 10  # 1 try + 1 retry, five times
    with pytest.raises(ProviderUnavailable, match="Circuit open"):
        await client.get_json("https://flaky.example/x")
    assert len(attempts) == 10  # the open breaker short-circuits without a request


async def test_client_errors_are_not_retried() -> None:
    attempts: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400)

    with pytest.raises(ProviderUnavailable, match="400"):
        await http(handler).get_json("https://api.example/x")
    assert len(attempts) == 1
