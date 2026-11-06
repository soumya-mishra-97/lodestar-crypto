"""News headlines from public RSS feeds, filtered to the asset.

XML is parsed with defusedxml (blocks XXE / billion-laughs). Headlines are
untrusted: the pipeline sanitises them and the LLM sees them only as fenced data.
"""

from __future__ import annotations

import asyncio
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import structlog
from defusedxml import ElementTree

from lodestar.domain.models import NewsItem
from lodestar.infrastructure.http import ResilientHttp

log = structlog.get_logger(__name__)
# Rebrands and common names that headlines use instead of the ticker.
ALIASES: dict[str, set[str]] = {"POL": {"polygon", "matic"}, "BTC": {"bitcoin"}, "ETH": {"ethereum", "ether"}}


def search_terms(name: str, symbol: str) -> set[str]:
    """'POL (ex-MATIC)' -> {'pol', 'matic', 'polygon'}: base name, ex-name in parentheses, aliases."""
    base, _, rest = name.partition("(")
    terms = {base.strip().lower(), symbol.lower(), *ALIASES.get(symbol.upper(), set())}
    if rest:
        terms.add(re.sub(r"^(ex|formerly)[- ]", "", rest.rstrip(") ").strip(), flags=re.I).lower())
    return {t for t in terms if len(t) >= 3}


class RssNewsProvider:
    def __init__(self, http: ResilientHttp, feeds: list[str]) -> None:
        self._http, self._feeds = http, feeds

    async def latest(self, *, name: str, symbol: str, limit: int) -> list[NewsItem]:
        results = await asyncio.gather(*(self._read(url) for url in self._feeds), return_exceptions=True)
        items = [i for r in results if isinstance(r, list) for i in r]
        if not items and any(isinstance(r, Exception) for r in results):
            raise next(r for r in results if isinstance(r, Exception))
        pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in search_terms(name, symbol)) + r")\b", re.I)
        relevant = [i for i in items if pattern.search(i.title)]
        relevant.sort(key=lambda i: i.published_at.timestamp() if i.published_at else 0, reverse=True)
        seen, unique = set(), []
        for item in relevant:
            if item.title.lower() not in seen:
                seen.add(item.title.lower())
                unique.append(item)
        return unique[:limit]

    async def _read(self, url: str) -> list[NewsItem]:
        raw = await self._http.get_bytes(url)
        root = ElementTree.fromstring(raw)
        source = urlparse(url).hostname or "rss"
        out = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link.startswith("https://"):
                continue
            published = None
            if pub := item.findtext("pubDate"):
                try:
                    published = parsedate_to_datetime(pub)
                except (TypeError, ValueError):
                    published = None
            out.append(NewsItem(title=title, source=source, url=link, published_at=published))
        return out
