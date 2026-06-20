"""LLM research agent that produces a structured brief for a symbol.

Gathers whatever data the configured keys allow (Alpaca price, Financial Datasets
fundamentals), hands it to Claude with the built-in web_search tool for current
news/context, and returns a :class:`ResearchBrief` the council can act on. Each data
source degrades gracefully: a missing key skips that source and is noted in the brief,
so the agent runs today on Alpaca creds alone and gets richer as keys are added.

The Anthropic client and gather function are injectable so tests never touch the
network. Educational/paper use only — the brief is an input to human voting, not advice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from trading_council.settings import Settings

_FINANCIAL_DATASETS_URL = "https://api.financialdatasets.ai/financial-metrics/snapshot"

# Strict schema — Claude must call submit_brief with exactly these fields.
_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "thesis": {"type": "string"},
        "risk": {"type": "string"},
        "exit_condition": {"type": "string"},
        "suggested_side": {"type": "string", "enum": ["buy", "sell", "none"]},
        "suggested_allocation_pct": {"type": "number"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary",
        "thesis",
        "risk",
        "exit_condition",
        "suggested_side",
        "suggested_allocation_pct",
        "confidence",
        "key_findings",
        "sources",
    ],
    "additionalProperties": False,
}


@dataclass
class ResearchBrief:
    symbol: str
    summary: str
    thesis: str
    risk: str
    exit_condition: str
    suggested_side: str
    suggested_allocation_pct: float
    confidence: str
    key_findings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def gather(symbol: str, settings: Settings) -> dict[str, Any]:
    """Collect whatever data the configured keys allow. Never raises on a missing source."""
    symbol_n = symbol.strip().upper()
    data: dict[str, Any] = {"symbol": symbol_n, "sources_unavailable": []}

    quote = _alpaca_quote(symbol_n, settings)
    if quote is not None:
        data["alpaca_quote"] = quote
    else:
        data["sources_unavailable"].append("alpaca (no/invalid credentials)")

    if settings.financial_datasets_api_key:
        fundamentals = _financial_datasets_snapshot(symbol_n, settings)
        if fundamentals is not None:
            data["fundamentals"] = fundamentals
        else:
            data["sources_unavailable"].append("financial_datasets (request failed)")
    else:
        data["sources_unavailable"].append("financial_datasets (no FINANCIAL_DATASETS_API_KEY)")

    return data


def _alpaca_quote(symbol: str, settings: Settings) -> dict[str, Any] | None:
    try:
        from trading_council.broker.alpaca import AlpacaBroker

        q = AlpacaBroker(settings).get_latest_quote(symbol)
        return {
            "bid_price": str(q.bid_price) if q.bid_price is not None else None,
            "ask_price": str(q.ask_price) if q.ask_price is not None else None,
        }
    except Exception:  # ponytail: any failure (no creds, no data feed) just skips Alpaca
        return None


def _financial_datasets_snapshot(symbol: str, settings: Settings) -> dict[str, Any] | None:
    try:
        import httpx

        resp = httpx.get(
            _FINANCIAL_DATASETS_URL,
            params={"ticker": symbol},
            headers={"X-API-Key": settings.financial_datasets_api_key or ""},
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:  # ponytail: bad key/symbol/network all degrade to "no fundamentals"
        return None


def research(
    symbol: str,
    settings: Settings,
    *,
    client: Any | None = None,
    gathered: dict[str, Any] | None = None,
) -> ResearchBrief:
    """Produce a :class:`ResearchBrief` for ``symbol``. ``client``/``gathered`` are injectable."""
    symbol_n = symbol.strip().upper()
    data = gathered if gathered is not None else gather(symbol_n, settings)
    client = client or _build_client(settings)

    tools = [
        {"type": "web_search_20260209", "name": "web_search"},
        {
            "name": "submit_brief",
            "description": "Record your final research brief. Call this once, last.",
            "strict": True,
            "input_schema": _BRIEF_SCHEMA,
        },
    ]
    prompt = (
        f"You are a research analyst for a paper-trading investment council (educational, "
        f"not real-money advice). Research {symbol_n} and write a brief the council will vote on.\n\n"
        f"Pre-gathered data (sources marked unavailable were skipped — note that as a caveat):\n"
        f"{json.dumps(data, indent=2)}\n\n"
        f"Use web_search for current price action, recent news, catalysts, earnings, and analyst "
        f"sentiment. Then call submit_brief once with: a thesis (why buy/sell now), the key risk, a "
        f"concrete exit_condition, a suggested side and allocation %, your confidence, key_findings, "
        f"and sources (URLs you used). Keep allocation conservative."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    for _ in range(8):
        resp = client.messages.create(
            model=settings.research_model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            tools=tools,
            messages=messages,
        )
        brief = next(
            (b for b in resp.content if b.type == "tool_use" and b.name == "submit_brief"),
            None,
        )
        if brief is not None:
            return ResearchBrief(symbol=symbol_n, **brief.input)

        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue  # server-side web_search hit its loop cap; re-send to resume
        # Model stopped without submitting — nudge it to finish.
        messages.append({"role": "user", "content": "Now call submit_brief with your findings."})

    raise RuntimeError(f"research agent did not submit a brief for {symbol_n}")


def _build_client(settings: Settings) -> Any:
    import anthropic

    # Anthropic() reads ANTHROPIC_API_KEY from the env; pass it explicitly when set in Settings.
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return anthropic.Anthropic()


def format_brief(brief: ResearchBrief) -> str:
    """Human-readable rendering for the CLI."""
    lines = [
        f"Research brief: {brief.symbol}  (confidence={brief.confidence})",
        f"suggested: {brief.suggested_side} {brief.suggested_allocation_pct}%",
        "",
        f"summary: {brief.summary}",
        f"thesis:  {brief.thesis}",
        f"risk:    {brief.risk}",
        f"exit:    {brief.exit_condition}",
    ]
    if brief.key_findings:
        lines += ["", "key findings:"] + [f"  - {f}" for f in brief.key_findings]
    if brief.sources:
        lines += ["", "sources:"] + [f"  - {s}" for s in brief.sources]
    return "\n".join(lines)
