"""Read-only balances for public addresses.

EVM chains via public JSON-RPC (eth_getBalance / ERC-20 balanceOf through eth_call),
Bitcoin via mempool.space. Only reads; no signing, no keys, no transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lodestar.domain.addresses import Chain
from lodestar.domain.errors import ProviderUnavailable
from lodestar.domain.models import WalletBalance
from lodestar.infrastructure.http import ResilientHttp

BALANCE_OF = "0x70a08231"  # keccak("balanceOf(address)")[:4]
MEMPOOL = "https://mempool.space/api/address"


@dataclass(frozen=True, slots=True)
class Token:
    contract: str
    decimals: int
    coingecko_id: str
    symbol: str
    name: str


NATIVE = {
    Chain.ETHEREUM: ("ethereum", "ETH", "Ethereum"),
    Chain.POLYGON: ("polygon-ecosystem-token", "POL", "POL (ex-MATIC)"),
}
TOKENS: dict[Chain, tuple[Token, ...]] = {
    Chain.ETHEREUM: (
        Token("0x455e53cbb86018ac2b8092fdcd39d8444affc3f6", 18, "polygon-ecosystem-token", "POL", "POL (ex-MATIC)"),
        Token("0x514910771af9ca656af840dff83e8264ecf986ca", 18, "chainlink", "LINK", "Chainlink"),
        Token("0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 8, "wrapped-bitcoin", "WBTC", "Wrapped Bitcoin"),
        Token("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6, "usd-coin", "USDC", "USDC"),
    ),
    Chain.POLYGON: (
        Token("0x7ceb23fd6bc0add59e62ac25578270cff1b9f619", 18, "weth", "WETH", "WETH"),
        Token("0xb0897686c545045afc77cf20ec7a532e3120e0f1", 18, "chainlink", "LINK", "Chainlink"),
        Token("0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", 6, "usd-coin", "USDC", "USDC"),
    ),
}


class PublicChainBalances:
    def __init__(self, http: ResilientHttp, rpc_urls: dict[str, str]) -> None:
        self._http, self._rpc = http, rpc_urls

    async def balances(self, chain: Chain, address: str) -> list[WalletBalance]:
        if chain is Chain.BITCOIN:
            return await self._bitcoin(address)
        return await self._evm(chain, address)

    async def _rpc_call(self, chain: Chain, method: str, params: list[Any]) -> str:
        url = self._rpc.get(chain.value)
        if not url:
            raise ProviderUnavailable(f"No RPC endpoint configured for {chain.value}")
        data = await self._http.post_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(data, dict) or "result" not in data:
            raise ProviderUnavailable(f"{chain.value} RPC error")
        return str(data["result"])

    async def _evm(self, chain: Chain, address: str) -> list[WalletBalance]:
        out = []
        native_wei = int(await self._rpc_call(chain, "eth_getBalance", [address, "latest"]), 16)
        cg, sym, name = NATIVE[chain]
        out.append(WalletBalance(cg, sym, name, native_wei / 1e18))
        padded = address.lower().removeprefix("0x").rjust(64, "0")
        for token in TOKENS[chain]:
            raw = await self._rpc_call(
                chain, "eth_call", [{"to": token.contract, "data": BALANCE_OF + padded}, "latest"]
            )
            amount = int(raw, 16) if raw not in ("0x", "") else 0
            if amount:
                out.append(WalletBalance(token.coingecko_id, token.symbol, token.name, amount / 10**token.decimals))
        return out

    async def _bitcoin(self, address: str) -> list[WalletBalance]:
        data = await self._http.get_json(f"{MEMPOOL}/{address}")
        stats = [data.get("chain_stats") or {}, data.get("mempool_stats") or {}]
        sats = sum(int(s.get("funded_txo_sum", 0)) - int(s.get("spent_txo_sum", 0)) for s in stats)
        return [WalletBalance("bitcoin", "BTC", "Bitcoin", max(sats, 0) / 1e8)]
