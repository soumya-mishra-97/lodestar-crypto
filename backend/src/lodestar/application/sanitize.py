"""Input hygiene for untrusted text that may reach the LLM (prompt-injection defence).

Sanitising is one layer of several. The others: the model has no tools and no
side effects, untrusted text is fenced and labelled as data, output is schema-
constrained, and every statement must cite evidence the validator can check.
"""

from __future__ import annotations

import re
import unicodedata

MAX_HEADLINE_CHARS = 240
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_TAGS = re.compile(r"<[^>]{0,200}>")
_INJECTION_HINTS = re.compile(
    r"(ignore (?:all |any )?(?:previous|prior|above) (?:instructions|prompts?)|disregard .{0,30}instructions|"
    r"you are now|system prompt|developer message|act as|new instructions|</?\s*(?:system|assistant|user)\b)",
    re.IGNORECASE,
)
_SEARCH_QUERY = re.compile(r"^[\w .\-]{1,64}$", re.UNICODE)
_COINGECKO_ID = re.compile(r"^[a-z0-9][a-z0-9\-]{0,99}$")


def clean_untrusted_text(text: str, max_chars: int = MAX_HEADLINE_CHARS) -> str:
    """Normalise, strip control/bidi characters and markup, collapse whitespace, truncate."""
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL.sub("", text)
    text = _TAGS.sub("", text)
    text = " ".join(text.split())
    return text[:max_chars]


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_HINTS.search(text))


def is_valid_search_query(q: str) -> bool:
    return bool(_SEARCH_QUERY.fullmatch(q.strip()))


def is_valid_coingecko_id(value: str) -> bool:
    return bool(_COINGECKO_ID.fullmatch(value))
