"""Human formatting of evidence values. Rounding stays within the verifier's tolerance."""

from __future__ import annotations

from lodestar.domain.evidence import Evidence


def usd(v: float) -> str:
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.2f}M"
    if a >= 1:
        return f"{sign}${a:,.2f}"
    return f"{sign}${a:.4g}"


def pct(v: float) -> str:
    return f"{v:.1f}%"


def count(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}" if a >= 1 else f"{v:.4g}"


def fmt(e: Evidence) -> str:
    v = e.value
    if isinstance(v, str):
        return v.replace("_", " ")
    match e.unit:
        case "usd":
            return usd(v)
        case "pct":
            return pct(v)
        case "count":
            return count(v)
        case "index":
            return f"{v:.1f}" if not float(v).is_integer() else f"{v:.0f}"
        case "days":
            return f"{v:.0f}"
        case _:
            return f"{v:.2f}"
