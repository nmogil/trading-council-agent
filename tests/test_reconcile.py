"""Tests for reconciliation. Broker is mocked — no network."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.broker.base import BrokerAccount, BrokerPosition
from trading_council.models import AuditLog, Order, PortfolioSnapshot, Position, Proposal
from trading_council.reconcile import reconcile

NOW = datetime(2026, 6, 22, 21, 15, tzinfo=timezone.utc)


def _account(**overrides) -> BrokerAccount:
    base = dict(
        account_id="acct-uuid-123",
        account_number_masked="****6789",
        status="ACTIVE",
        currency="USD",
        cash_cents=15_000,
        equity_cents=20_000,
        buying_power_cents=30_000,
        trading_blocked=False,
        account_blocked=False,
        pattern_day_trader=False,
    )
    base.update(overrides)
    return BrokerAccount(**base)


class FakeBroker:
    def __init__(self, account, positions):
        self._account = account
        self._positions = positions

    def get_account(self):
        return self._account

    def get_positions(self):
        return self._positions


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def test_writes_snapshot_with_sanitized_json(session):
    broker = FakeBroker(_account(), [])
    result = reconcile(session, broker=broker, now=NOW)

    snap = session.exec(select(PortfolioSnapshot)).one()
    assert snap.cash_cents == 15_000
    assert snap.equity_cents == 20_000
    assert snap.buying_power_cents == 30_000
    assert snap.captured_at == NOW.replace(tzinfo=None)  # SQLite round-trips naive

    raw = json.loads(snap.raw_json)
    assert raw["account_number_masked"] == "****6789"
    # No full account number, no account id, no secrets leak into the snapshot.
    assert "account_id" not in raw
    assert "acct-uuid-123" not in snap.raw_json
    assert result.equity_cents == 20_000


def test_upserts_positions(session):
    session.add(Position(symbol="QQQ", qty=Decimal("1"), market_value_cents=100, updated_at=NOW))
    session.commit()

    broker = FakeBroker(
        _account(),
        [
            BrokerPosition(
                symbol="QQQ",
                qty=Decimal("3"),
                side="long",
                avg_entry_price_cents=40_000,
                market_value_cents=120_000,
            ),
            BrokerPosition(symbol="SPY", qty=Decimal("2"), side="long", market_value_cents=90_000),
        ],
    )
    result = reconcile(session, broker=broker, now=NOW)

    qqq = session.get(Position, "QQQ")
    assert qqq.qty == Decimal("3")
    assert qqq.market_value_cents == 120_000
    assert qqq.avg_entry_price_cents == 40_000
    assert qqq.updated_at == NOW.replace(tzinfo=None)  # SQLite round-trips naive
    assert session.get(Position, "SPY").qty == Decimal("2")
    assert result.positions_upserted == 2


def test_audit_log_records_summary(session):
    broker = FakeBroker(_account(), [])
    reconcile(session, broker=broker, actor="cron", now=NOW)

    log = session.exec(select(AuditLog).where(AuditLog.action == "reconcile")).one()
    assert log.actor == "cron"
    details = json.loads(log.details_json)
    assert details["equity_cents"] == 20_000
    assert details["positions_upserted"] == 0


def test_diff_missing_from_broker(session):
    # A sent buy order for QQQ exists, but the broker reports no QQQ position.
    session.add(
        Order(
            id="o1",
            proposal_id="2026-W26-A",
            broker_order_id="b1",
            client_order_id="c1",
            symbol="QQQ",
            side="buy",
            notional_cents=4_000,
            status="filled",
            mode="paper",
            raw_request_json="{}",
        )
    )
    session.commit()

    broker = FakeBroker(_account(), [])
    result = reconcile(session, broker=broker, now=NOW)
    assert result.missing_from_broker == ["QQQ"]
    assert result.extra_on_broker == []


def test_diff_extra_on_broker(session):
    # Broker reports TSLA we have no order/proposal/position for.
    broker = FakeBroker(
        _account(),
        [BrokerPosition(symbol="TSLA", qty=Decimal("1"), side="long", market_value_cents=50_000)],
    )
    result = reconcile(session, broker=broker, now=NOW)
    assert result.extra_on_broker == ["TSLA"]
    assert result.missing_from_broker == []


def test_known_broker_symbol_is_not_extra(session):
    session.add(
        Proposal(
            id="2026-W26-A",
            symbol="SPY",
            side="buy",
            allocation_pct=Decimal("10"),
            thesis="t",
            risk="r",
            exit_condition="e",
            status="approved",
            created_by="noah",
        )
    )
    session.commit()
    broker = FakeBroker(
        _account(),
        [BrokerPosition(symbol="SPY", qty=Decimal("1"), side="long", market_value_cents=50_000)],
    )
    result = reconcile(session, broker=broker, now=NOW)
    assert result.extra_on_broker == []



def test_removes_positions_absent_from_broker_mirror(session):
    session.add(Position(symbol="OLD", qty=Decimal("1"), market_value_cents=100, updated_at=NOW))
    session.add(Position(symbol="QQQ", qty=Decimal("1"), market_value_cents=100, updated_at=NOW))
    session.commit()

    broker = FakeBroker(
        _account(),
        [BrokerPosition(symbol="QQQ", qty=Decimal("2"), side="long", market_value_cents=200)],
    )
    result = reconcile(session, broker=broker, now=NOW)

    assert session.get(Position, "OLD") is None
    assert session.get(Position, "QQQ").qty == Decimal("2")
    assert result.positions_removed == 1
