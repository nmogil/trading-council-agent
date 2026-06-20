"""Research agent: graceful gather degradation + brief synthesis via an injected client."""

from __future__ import annotations

from types import SimpleNamespace

from trading_council.research import ResearchBrief, gather, research
from trading_council.settings import Settings


def _settings(**env) -> Settings:
    # No keys by default → every external source should be skipped, not crash.
    return Settings(_env_file=None, **env)


def test_gather_degrades_without_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
    data = gather("aapl", _settings())
    assert data["symbol"] == "AAPL"
    # Both sources unavailable, but no exception and the caveats are recorded.
    assert any("alpaca" in s for s in data["sources_unavailable"])
    assert any("financial_datasets" in s for s in data["sources_unavailable"])


class _FakeClient:
    """Returns a single submit_brief tool_use, like Claude finishing its research."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **_kwargs):
            self._outer.calls += 1
            block = SimpleNamespace(
                type="tool_use", name="submit_brief", input=self._outer._payload
            )
            return SimpleNamespace(content=[block], stop_reason="tool_use")

    @property
    def messages(self):
        return self._Messages(self)


def test_research_returns_brief_from_tool_call():
    payload = {
        "summary": "s",
        "thesis": "buy the dip",
        "risk": "rates",
        "exit_condition": "below 180",
        "suggested_side": "buy",
        "suggested_allocation_pct": 5,
        "confidence": "medium",
        "key_findings": ["beat earnings"],
        "sources": ["https://example.com"],
    }
    client = _FakeClient(payload)
    brief = research("aapl", _settings(), client=client, gathered={"symbol": "AAPL"})
    assert isinstance(brief, ResearchBrief)
    assert brief.symbol == "AAPL"
    assert brief.suggested_side == "buy"
    assert brief.thesis == "buy the dip"
    assert client.calls == 1
