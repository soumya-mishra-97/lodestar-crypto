"""CSV holdings import: tolerant headers, strict values, line-numbered errors.

Accepted columns (case-insensitive, any order):
  coin | coingecko_id | id     CoinGecko id (preferred: unambiguous)
  symbol | ticker               used when no coin id is given
  quantity | amount | qty       required, >= 0
  avg_cost_usd | avg_cost | cost_basis | price   optional, >= 0, per token
  notes                         optional
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

from lodestar.application.sanitize import clean_untrusted_text, is_valid_coingecko_id
from lodestar.domain.addresses import looks_like_secret

MAX_ROWS = 500
MAX_BYTES = 200_000
_ALIASES = {
    "coingecko_id": ("coin", "coingecko_id", "id", "coin_id"),
    "symbol": ("symbol", "ticker", "asset"),
    "quantity": ("quantity", "amount", "qty", "balance"),
    "avg_cost_usd": ("avg_cost_usd", "avg_cost", "cost_basis", "price", "cost"),
    "notes": ("notes", "note", "memo"),
}


@dataclass(frozen=True, slots=True)
class CsvHolding:
    line: int
    coingecko_id: str | None
    symbol: str | None
    quantity: float
    avg_cost_usd: float | None
    notes: str | None


@dataclass(slots=True)
class CsvParseResult:
    rows: list[CsvHolding] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)


def _number(raw: str) -> float | None:
    text = raw.strip().replace(",", "").replace("$", "").replace("_", "")
    if not text:
        return None
    value = float(text)  # raises ValueError
    if not math.isfinite(value) or value < 0:
        raise ValueError("must be a non-negative number")
    return value


def parse_holdings_csv(text: str) -> CsvParseResult:
    out = CsvParseResult()
    if len(text.encode()) > MAX_BYTES:
        out.errors.append((0, f"file is larger than {MAX_BYTES // 1000} KB"))
        return out
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        out.errors.append((0, "the file has no header row"))
        return out
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    column = {
        canonical: next((headers[a] for a in aliases if a in headers), None) for canonical, aliases in _ALIASES.items()
    }
    if column["quantity"] is None or (column["coingecko_id"] is None and column["symbol"] is None):
        out.errors.append((1, "header must include a quantity column and a coin (CoinGecko id) or symbol column"))
        return out

    for line, row in enumerate(reader, start=2):
        if len(out.rows) >= MAX_ROWS:
            out.errors.append((line, f"stopped after {MAX_ROWS} rows"))
            break

        def cell(name: str, r: dict[str, str | None] = row) -> str:
            col = column[name]
            return (r.get(col) or "").strip() if col else ""

        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        if any(looks_like_secret(v) for v in row.values() if isinstance(v, str)):
            out.errors.append((line, "contains what looks like a private key or seed phrase; row ignored"))
            continue
        coin = cell("coingecko_id").lower() or None
        symbol = cell("symbol").upper() or None
        if coin and not is_valid_coingecko_id(coin):
            out.errors.append((line, f"invalid CoinGecko id '{coin[:40]}'"))
            continue
        if not coin and not symbol:
            out.errors.append((line, "missing coin id or symbol"))
            continue
        try:
            quantity = _number(cell("quantity"))
            cost = _number(cell("avg_cost_usd"))
        except ValueError as exc:
            out.errors.append((line, f"invalid number ({exc})"))
            continue
        if quantity is None:
            out.errors.append((line, "missing quantity"))
            continue
        notes = clean_untrusted_text(cell("notes"), 1000) or None
        out.rows.append(CsvHolding(line, coin, symbol[:20] if symbol else None, quantity, cost, notes))
    return out
