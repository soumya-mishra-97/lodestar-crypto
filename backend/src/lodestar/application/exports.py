"""Report export to Markdown (the PDF renderer consumes the same outline)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TAG_LABEL = {
    "fact": "FACT",
    "calculation": "CALC",
    "interpretation": "INTERP",
    "scenario": "SCENARIO",
    "assumption": "ASSUMPTION",
}
SECTION_TITLES = {"thesis": "Thesis", "opportunities": "Opportunities", "risks": "Risks", "watch": "What to watch"}
STATUS_LABEL = {"pending_approval": "Pending approval", "approved": "Approved", "rejected": "Rejected"}
PLAN_SECTIONS = {
    "setup": "Setup",
    "timing": "Timing: entry zone, trigger, invalidation",
    "scenarios": "Scenarios (historical analogs)",
    "risk": "Risk and size",
    "invalidation": "What invalidates it",
    "evidence": "Supporting evidence",
    "assumptions": "Assumptions",
}


@dataclass(frozen=True, slots=True)
class Block:
    """One element of the export outline: heading, paragraph, claim list, table or note."""

    kind: str  # "h1" | "h2" | "h3" | "p" | "claims" | "table" | "small"
    text: str = ""
    claims: tuple[Mapping[str, Any], ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


def _fmt_value(e: Mapping[str, Any]) -> str:
    v, unit = e["value"], e["unit"]
    if isinstance(v, str):
        return v.replace("_", " ")
    if unit == "usd":
        return f"${v:,.2f}" if abs(v) >= 1 else f"${v:.4g}"
    if unit == "pct":
        return f"{v:.2f}%"
    if unit in ("count", "days"):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.4f}"
    return f"{v:.4g}"


def _price(v: float) -> str:
    return f"${v:,.2f}" if abs(v) >= 1 else f"${v:.4g}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _header(report: Mapping[str, Any], title: str) -> Iterator[Block]:
    c = report["content"]
    asset, draft = c["asset"], c["draft"]
    yield Block("h1", f"{asset['name']} ({asset['symbol']}) · {title}")
    yield Block(
        "small",
        f"Generated {c['generated_at'][:16].replace('T', ' ')} UTC · {report['kind'].replace('_', '-')} · "
        f"status: {STATUS_LABEL.get(report['status'], report['status'])} · data: {c['data_mode']} · "
        f"writer: {draft['writer']} · pipeline {c['pipeline_version']}",
    )
    if c["data_mode"] == "demo":
        yield Block("p", "DEMO DATA: prices and metrics in this report are synthetic, not real market data.")
    yield Block("claims", claims=(draft["headline"],))


def _footer(report: Mapping[str, Any], cited: set[str]) -> Iterator[Block]:
    c = report["content"]
    evidence: Sequence[Mapping[str, Any]] = c.get("evidence") or []
    yield Block("h2", f"Evidence cited ({len(cited)} of {len(evidence)} items)")
    yield Block(
        "table",
        rows=(
            ("ID", "Metric", "Value", "Kind", "Source"),
            *((e["id"], e["label"], _fmt_value(e), e["kind"], e["source"]) for e in evidence if e["id"] in cited),
        ),
    )
    v = c.get("verification") or {}
    yield Block(
        "small",
        f"Verification: {'passed' if v.get('passed') else 'not passed'} · "
        f"{v.get('checked_claims', 0)} claims checked · "
        f"{v.get('repairs', 0)} repair loop(s)"
        + (f" · decision note: {report['decision_note']}" if report.get("decision_note") else ""),
    )
    yield Block("h2", "Disclaimer")
    yield Block("p", c["disclaimer"])


def _plan_outline(report: Mapping[str, Any]) -> Iterator[Block]:
    c = report["content"]
    card, draft = c["card"], c["draft"]
    yield from _header(report, "Lodestar trade plan (paper trading only)")
    setup, timing, size, risk = card["setup"], card["timing"], card["size"], card["risk"]
    yield Block("h2", "Trade plan card")
    yield Block(
        "table",
        rows=(
            ("Item", "Value"),
            ("Setup", f"{setup['kind'].replace('_', ' ')} ({setup['status']})"),
            ("Trigger", f"{setup['trigger_text']} ({_price(timing['trigger_level'])})"),
            ("Entry zone", f"{_price(timing['entry_zone'][0])} to {_price(timing['entry_zone'][1])}"),
            ("Invalidation", _price(timing["invalidation"])),
            ("Profit-taking rule", _price(timing["profit_level"])),
            ("Risk level", f"{risk['level'].replace('_', ' ')} ({risk['score']:.0f}/100)"),
            ("Paper size", f"{size['units']:.6g} units · {_price(size['notional_usd'])}"),
            ("Max loss", f"{_price(size['max_loss_usd'])} (loss at stop {_price(size['loss_at_stop_usd'])})"),
            ("Size limited by", size["binding"].replace("_", " ")),
        ),
    )
    sc = card["scenarios"]
    o = sc["overall"]
    yield Block("h2", f"Scenarios over {sc['horizon_days']} days")
    yield Block(
        "small",
        f"{o['n']} non-overlapping historical analogs of this setup · sample reliability: {o['reliability']} · "
        f"costs of {sc['cost_pct']:.2f}% per round trip included · intervals are 95%",
    )
    yield Block(
        "table",
        rows=(
            ("Scenario", "Definition", "Frequency (95% CI)", "Mean", "Median", "Worst drawdown"),
            *(
                (
                    s["name"],
                    s["definition"],
                    f"{s['count']}/{s['total']} = {_pct(s['probability_pct'])}"
                    + (
                        f" ({s['probability_ci'][0]:.0f}-{s['probability_ci'][1]:.0f}%)"
                        if s.get("probability_ci")
                        else ""
                    ),
                    _pct(s["mean_pct"]),
                    _pct(s["median_pct"]),
                    _pct(s["worst_drawdown_pct"]),
                )
                for s in sc["scenarios"]
            ),
        ),
    )
    bt = card["backtest"]
    yield Block("h2", "Backtest (fees and slippage included)")
    yield Block(
        "table",
        rows=(
            ("Sample", "Trades", "Win rate", "Total return", "Max drawdown", "Buy and hold"),
            *(
                (
                    label,
                    f"{m['trades']}",
                    _pct(m["win_rate_pct"]),
                    _pct(m["total_return_pct"]),
                    _pct(m["max_drawdown_pct"]),
                    _pct(m["buy_hold_return_pct"]),
                )
                for label, m in (
                    ("In-sample (fitted)", bt["in_sample"]),
                    ("Out-of-sample", bt["out_of_sample"]),
                    ("Walk-forward", bt["walk_forward"]),
                )
            ),
        ),
    )
    if bt["warnings"]:
        yield Block("h3", "Overfitting and sample warnings")
        yield Block("p", " ".join(bt["warnings"]))
    for section, title in PLAN_SECTIONS.items():
        if draft.get(section):
            yield Block("h2", title)
            yield Block("claims", claims=tuple(draft[section]))
    yield from _footer(report, {i for _, cl in _all_claims(draft) for i in cl.get("evidence_ids", [])})


def outline(report: Mapping[str, Any]) -> Iterator[Block]:
    if report["kind"] == "trade_plan":
        yield from _plan_outline(report)
        return
    c = report["content"]
    draft = c["draft"]
    yield from _header(report, "Lodestar report")

    rows = [("Horizon", "Stance", "Signal score", "Risk level", "Risk score", "Confidence")]
    for h in ("short_term", "long_term"):
        a = c["assessments"][h]
        rows.append(
            (
                h.replace("_", "-").capitalize(),
                a["stance"],
                f"{a['score']:.0f}/100",
                a["risk"]["level"].replace("_", " "),
                f"{a['risk']['score']:.0f}/100",
                f"{a['confidence'] * 100:.0f}%",
            )
        )
    yield Block("h2", "Assessments")
    yield Block("table", rows=tuple(rows))

    for h, title in (
        ("short_term", "Short term (days to four weeks)"),
        ("long_term", "Long term (six months or more)"),
    ):
        yield Block("h2", title)
        for section, label in SECTION_TITLES.items():
            items = draft[h].get(section) or []
            if items:
                yield Block("h3", label)
                yield Block("claims", claims=tuple(items))
        factors = c["assessments"][h]["risk"]["factors"]
        if factors:
            yield Block("h3", "Risk factors")
            yield Block(
                "table",
                rows=(
                    ("Factor", "Points", "Detail"),
                    *((f["name"].replace("_", " "), f"{f['points']:g}", f["detail"]) for f in factors),
                ),
            )

    for key, title in (
        ("portfolio", "Your portfolio"),
        ("data_quality", "Data quality"),
        ("uncertainties", "Assumptions and uncertainties"),
    ):
        if draft.get(key):
            yield Block("h2", title)
            yield Block("claims", claims=tuple(draft[key]))
    if c.get("data_gaps"):
        yield Block("h3", "Data gaps")
        yield Block("p", "; ".join(c["data_gaps"]))

    yield from _footer(report, {i for _, claim in _all_claims(draft) for i in claim.get("evidence_ids", [])})


def _all_claims(draft: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    yield "headline", draft["headline"]
    for section in PLAN_SECTIONS:
        for claim in draft.get(section) or []:
            yield section, claim
    for h in ("short_term", "long_term"):
        if h not in draft:
            continue
        for section in SECTION_TITLES:
            for claim in draft[h].get(section) or []:
                yield f"{h}.{section}", claim
    for key in ("portfolio", "data_quality", "uncertainties"):
        for claim in draft.get(key) or []:
            yield key, claim


def claim_line(claim: Mapping[str, Any]) -> str:
    ids = ", ".join(claim.get("evidence_ids") or [])
    return f"[{TAG_LABEL.get(claim['tag'], claim['tag'].upper())}] {claim['text']}" + (f" ({ids})" if ids else "")


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for b in outline(report):
        match b.kind:
            case "h1":
                lines += [f"# {b.text}", ""]
            case "h2":
                lines += [f"## {b.text}", ""]
            case "h3":
                lines += [f"### {b.text}", ""]
            case "p":
                lines += [b.text, ""]
            case "small":
                lines += [f"_{b.text}_", ""]
            case "claims":
                lines += [f"- {claim_line(c)}" for c in b.claims] + [""]
            case "table":
                header, *body = b.rows
                lines.append("| " + " | ".join(_md_escape(x) for x in header) + " |")
                lines.append("|" + "---|" * len(header))
                lines += ["| " + " | ".join(_md_escape(x) for x in row) + " |" for row in body]
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_filename(report: Mapping[str, Any], ext: str) -> str:
    c = report["content"]
    return f"lodestar-{c['asset']['symbol'].lower()}-{c['generated_at'][:10]}-{str(report['id'])[:8]}.{ext}"
