"""Tests for the portfolio summary report."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine

from trading_council.models import PortfolioSnapshot, Position, Proposal
from trading_council.reports import portfolio_summary
from trading_council.settings import Settings

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def _paper() -> Settings:
    return Settings(TRADING_COUNCIL_MODE="paper")


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def test_empty_states(session):
    out = portfolio_summary(session, settings=_paper(), now=NOW)
    assert "Trading Council Portfolio — paper" in out
    assert "No portfolio snapshot yet" in out
    assert "Positions:\n- none" in out
    assert "Open proposals:\n- none" in out


def test_renders_snapshot_positions_and_proposals(session):
    session.add(
        PortfolioSnapshot(
            captured_at=NOW,
            cash_cents=15_000,
            equity_cents=20_000,
            buying_power_cents=30_000,
            raw_json="{}",
        )
    )
    session.add(
        Position(symbol="QQQ", qty=Decimal("3"), market_value_cents=120_000, updated_at=NOW)
    )
    session.add(
        Proposal(
            id="2026-W26-A",
            symbol="SPY",
            side="buy",
            allocation_pct=Decimal("10"),
            thesis="t",
            risk="r",
            exit_condition="e",
            status="voting",
            created_by="noah",
            created_at=NOW,
        )
    )
    session.commit()

    out = portfolio_summary(session, settings=_paper(), now=NOW)
    assert "Equity: $200.00" in out
    assert "Cash: $150.00" in out
    assert "Buying power: $300.00" in out
    assert "- QQQ: qty 3, market value $1200.00" in out
    assert "- 2026-W26-A: SPY buy 10%" in out


def test_latest_snapshot_used(session):
    earlier = NOW.replace(hour=9)
    session.add(
        PortfolioSnapshot(captured_at=earlier, cash_cents=1, equity_cents=1, raw_json="{}")
    )
    session.add(
        PortfolioSnapshot(captured_at=NOW, cash_cents=99_900, equity_cents=99_900, raw_json="{}")
    )
    session.commit()
    out = portfolio_summary(session, settings=_paper(), now=NOW)
    assert "Equity: $999.00" in out
