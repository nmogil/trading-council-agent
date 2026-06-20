"""Tests for execution staging. No network; in-memory SQLite."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.execution import ExecutionError, RiskRejected, stage_order_for_proposal
from trading_council.models import AuditLog, Order, PortfolioSnapshot, Position, Proposal
from trading_council.settings import Settings

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def _paper(**overrides) -> Settings:
    base = dict(TRADING_COUNCIL_MODE="paper", TRADING_COUNCIL_KILL_SWITCH="false")
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        sess.add(
            Proposal(
                id="2026-W26-A",
                symbol="QQQ",
                side="buy",
                allocation_pct=Decimal("20"),
                thesis="t",
                risk="r",
                exit_condition="e",
                status="approved",
                created_by="noah",
            )
        )
        # $200 equity -> 20% = 4000c, under the $50 (5000c) notional cap.
        sess.add(PortfolioSnapshot(cash_cents=20_000, equity_cents=20_000, raw_json="{}"))
        sess.commit()
        yield sess


def test_stage_creates_staged_order_with_notional(session):
    order = stage_order_for_proposal(
        session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW
    )
    assert order.status == "staged"
    assert order.symbol == "QQQ"
    assert order.notional_cents == 4_000  # 20% of 20_000c
    assert order.client_order_id == "tc-2026-W26-A"
    assert order.mode == "paper"


def test_stage_writes_audit(session):
    stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)
    log = session.exec(
        select(AuditLog).where(AuditLog.action == "stage_order")
    ).one()
    assert log.decision == "staged"


def test_stage_rejects_unapproved_proposal(session):
    proposal = session.get(Proposal, "2026-W26-A")
    proposal.status = "voting"
    session.add(proposal)
    session.commit()
    with pytest.raises(ExecutionError, match="not approved"):
        stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)


def test_stage_rejects_duplicate_order(session):
    stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)
    with pytest.raises(ExecutionError, match="already exists"):
        stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)


def test_stage_requires_portfolio_snapshot(session):
    for snap in session.exec(select(PortfolioSnapshot)).all():
        session.delete(snap)
    session.commit()
    with pytest.raises(ExecutionError, match="snapshot"):
        stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)


def test_stage_blocked_by_kill_switch_creates_no_order(session):
    with pytest.raises(RiskRejected, match="kill switch"):
        stage_order_for_proposal(
            session,
            "2026-W26-A",
            actor="cli",
            settings=_paper(TRADING_COUNCIL_KILL_SWITCH="true"),
            now=NOW,
        )
    assert session.exec(select(Order)).all() == []
    # The rejection is still audited.
    log = session.exec(select(AuditLog).where(AuditLog.action == "stage_order")).one()
    assert log.decision == "rejected"


def test_stage_blocked_when_existing_position_too_large(session):
    # Existing 4000c + new 4000c = 8000c of 20000c = 40% > 25% max allocation.
    session.add(Position(symbol="QQQ", qty=Decimal("1"), market_value_cents=4_000))
    session.commit()
    with pytest.raises(RiskRejected):
        stage_order_for_proposal(session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW)
