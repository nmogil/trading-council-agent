"""Tests for paper order submission. Broker is mocked — no network."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.broker.base import BrokerOrder
from trading_council.execution import (
    ExecutionError,
    stage_order_for_proposal,
    submit_order_for_proposal,
)
from trading_council.models import AuditLog, PortfolioSnapshot, Proposal
from trading_council.settings import Settings

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


def _paper(**overrides) -> Settings:
    base = dict(
        TRADING_COUNCIL_MODE="paper",
        TRADING_COUNCIL_KILL_SWITCH="false",
        ALPACA_PAPER_API_KEY="k",
        ALPACA_PAPER_SECRET_KEY="s",
    )
    base.update(overrides)
    return Settings(**base)


class FakeBroker:
    def __init__(self):
        self.calls = []

    def place_market_order(self, *, symbol, side, notional_cents, client_order_id):
        self.calls.append(client_order_id)
        return BrokerOrder(
            broker_order_id="broker-1",
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            status="accepted",
            notional_cents=notional_cents,
            filled_qty=Decimal("0"),
        )


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
        sess.add(PortfolioSnapshot(cash_cents=20_000, equity_cents=20_000, raw_json="{}"))
        sess.commit()
        yield sess


def _stage(session):
    return stage_order_for_proposal(
        session, "2026-W26-A", actor="cli", settings=_paper(), now=NOW
    )


def test_submit_places_order_and_stores_sanitized_response(session):
    _stage(session)
    broker = FakeBroker()
    order = submit_order_for_proposal(
        session, "2026-W26-A", actor="cli", broker=broker, settings=_paper(), now=NOW
    )
    assert broker.calls == ["tc-2026-W26-A"]
    assert order.broker_order_id == "broker-1"
    assert order.status == "accepted"
    assert order.submitted_at == NOW
    stored = json.loads(order.raw_response_json)
    assert stored["broker_order_id"] == "broker-1"
    assert stored["filled_qty"] == "0"  # Decimal serialized as string


def test_submit_audits_risk_and_broker_metadata(session):
    _stage(session)
    submit_order_for_proposal(
        session, "2026-W26-A", actor="cli", broker=FakeBroker(), settings=_paper(), now=NOW
    )
    log = session.exec(select(AuditLog).where(AuditLog.action == "submit_order")).one()
    assert log.decision == "accepted"
    details = json.loads(log.details_json)
    assert details["broker_order_id"] == "broker-1"
    assert details["risk_allowed"] is True


def test_submit_is_idempotent_no_duplicate_broker_order(session):
    _stage(session)
    broker = FakeBroker()
    first = submit_order_for_proposal(
        session, "2026-W26-A", actor="cli", broker=broker, settings=_paper(), now=NOW
    )
    second = submit_order_for_proposal(
        session, "2026-W26-A", actor="cli", broker=broker, settings=_paper(), now=NOW
    )
    assert broker.calls == ["tc-2026-W26-A"]  # placed exactly once
    assert first.broker_order_id == second.broker_order_id


def test_submit_without_staged_order_fails(session):
    with pytest.raises(ExecutionError, match="no staged order"):
        submit_order_for_proposal(
            session, "2026-W26-A", actor="cli", broker=FakeBroker(), settings=_paper(), now=NOW
        )


def test_live_mode_fails_closed(session):
    _stage(session)
    broker = FakeBroker()
    live = _paper(
        TRADING_COUNCIL_MODE="live",
        TRADING_COUNCIL_LIVE_ENABLED="true",
        ALPACA_LIVE_API_KEY="k",
        ALPACA_LIVE_SECRET_KEY="s",
    )
    with pytest.raises(ExecutionError, match="paper mode only"):
        submit_order_for_proposal(
            session, "2026-W26-A", actor="cli", broker=broker, settings=live, now=NOW
        )
    assert broker.calls == []  # broker never touched in live mode



def test_submit_rechecks_proposal_is_still_approved(session):
    _stage(session)
    proposal = session.get(Proposal, "2026-W26-A")
    proposal.status = "cancelled"
    session.add(proposal)
    session.commit()
    broker = FakeBroker()

    with pytest.raises(ExecutionError, match="not approved"):
        submit_order_for_proposal(
            session, "2026-W26-A", actor="cli", broker=broker, settings=_paper(), now=NOW
        )

    assert broker.calls == []



def test_submit_rejects_stale_staged_notional_after_equity_change(session):
    _stage(session)
    # A later snapshot changes current equity from 20_000c to 10_000c; the staged
    # 4_000c order is now stale and must not be sent to the broker.
    session.add(PortfolioSnapshot(cash_cents=10_000, equity_cents=10_000, raw_json="{}"))
    session.commit()
    broker = FakeBroker()

    with pytest.raises(ExecutionError, match="stale"):
        submit_order_for_proposal(
            session, "2026-W26-A", actor="cli", broker=broker, settings=_paper(), now=NOW
        )

    assert broker.calls == []
