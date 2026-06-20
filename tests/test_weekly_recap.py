"""Tests for the weekly recap report."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine

from trading_council.models import AuditLog, Order, PortfolioSnapshot, Proposal
from trading_council.reports import weekly_recap
from trading_council.settings import Settings

# Monday 2026-06-22 .. Sunday 2026-06-28 is the ISO week containing NOW.
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
MONDAY = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
LAST_WEEK = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)


def _paper() -> Settings:
    return Settings(TRADING_COUNCIL_MODE="paper")


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def test_empty_states(session):
    out = weekly_recap(session, settings=_paper(), now=NOW)
    assert "Week: 2026-06-22 to 2026-06-28" in out
    assert "no snapshots this week" in out
    assert "Trades executed/submitted: 0" in out
    assert "Proposals accepted: 0" in out
    assert "Proposals rejected: 0" in out
    assert "not real P/L" in out


def test_equity_change_within_week(session):
    session.add(
        PortfolioSnapshot(captured_at=MONDAY, cash_cents=0, equity_cents=20_000, raw_json="{}")
    )
    session.add(
        PortfolioSnapshot(captured_at=NOW, cash_cents=0, equity_cents=25_000, raw_json="{}")
    )
    # A snapshot from last week must not be picked as the beginning.
    session.add(
        PortfolioSnapshot(captured_at=LAST_WEEK, cash_cents=0, equity_cents=1, raw_json="{}")
    )
    session.commit()

    out = weekly_recap(session, settings=_paper(), now=NOW)
    assert "Beginning equity: $200.00" in out
    assert "Ending equity: $250.00" in out
    assert "Change: $50.00" in out


def test_counts_trades_and_proposals_in_week(session):
    session.add(
        Order(
            id="o1",
            proposal_id="2026-W26-A",
            client_order_id="c1",
            symbol="QQQ",
            side="buy",
            notional_cents=4_000,
            status="accepted",
            mode="paper",
            submitted_at=NOW,
            raw_request_json="{}",
        )
    )
    # Rejected and out-of-week orders are excluded.
    session.add(
        Order(
            id="o2",
            proposal_id="2026-W26-B",
            client_order_id="c2",
            symbol="SPY",
            side="buy",
            notional_cents=4_000,
            status="rejected",
            mode="paper",
            submitted_at=NOW,
            raw_request_json="{}",
        )
    )
    session.add(
        Order(
            id="o3",
            proposal_id="2026-W25-A",
            client_order_id="c3",
            symbol="TLT",
            side="buy",
            notional_cents=4_000,
            status="accepted",
            mode="paper",
            submitted_at=LAST_WEEK,
            raw_request_json="{}",
        )
    )
    session.add(
        AuditLog(
            created_at=MONDAY,
            actor="cli",
            action="close_vote",
            entity_type="proposal",
            entity_id="2026-W25-A",
            decision="approved",
            details_json="{}",
        )
    )
    session.add(
        AuditLog(
            created_at=MONDAY,
            actor="cli",
            action="close_vote",
            entity_type="proposal",
            entity_id="2026-W26-C",
            decision="rejected",
            details_json="{}",
        )
    )
    # Created this week but not closed this week should not count as accepted/rejected yet.
    session.add(
        Proposal(
            id="2026-W26-D",
            symbol="GLD",
            side="buy",
            allocation_pct=Decimal("10"),
            thesis="t",
            risk="r",
            exit_condition="e",
            status="approved",
            created_by="noah",
            created_at=MONDAY,
        )
    )
    session.commit()

    out = weekly_recap(session, settings=_paper(), now=NOW)
    assert "Trades executed/submitted: 1" in out
    assert "- QQQ buy $40.00 (accepted)" in out
    assert "Proposals accepted: 1" in out
    assert "Proposals rejected: 1" in out



def test_counts_proposals_by_close_vote_audit_date_not_created_at(session):
    # Created last week, approved this week: should count this week because the
    # governance outcome happened this week.
    session.add(
        Proposal(
            id="2026-W25-A",
            symbol="QQQ",
            side="buy",
            allocation_pct=Decimal("10"),
            thesis="t",
            risk="r",
            exit_condition="e",
            status="approved",
            created_by="noah",
            created_at=LAST_WEEK,
        )
    )
    session.add(
        AuditLog(
            created_at=MONDAY,
            actor="cli",
            action="close_vote",
            entity_type="proposal",
            entity_id="2026-W25-A",
            decision="approved",
            details_json="{}",
        )
    )
    session.commit()

    out = weekly_recap(session, settings=_paper(), now=NOW)
    assert "Proposals accepted: 1" in out
