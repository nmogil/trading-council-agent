"""Reconciliation: pull broker account/positions and update the local ledger.

Read-only against the broker; writes only a ``PortfolioSnapshot``, upserted
``Position`` rows, and an audit entry. The stored snapshot JSON is sanitized — it
holds the masked account number and safe scalar fields, never the full account
number, account id, or any secret.

The diff is deliberately conservative and deterministic so a human can eyeball it:

* ``missing_from_broker`` — symbols of buy orders we sent to the broker (have a
  ``broker_order_id``) that no longer show up as a broker position.
* ``extra_on_broker`` — broker position symbols we don't recognize from any local
  position, order, or proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from trading_council.audit import log_event
from trading_council.broker.base import Broker, BrokerAccount
from trading_council.models import Order, PortfolioSnapshot, Position, Proposal, utcnow


@dataclass(frozen=True)
class ReconcileResult:
    snapshot_id: int | None
    cash_cents: int
    equity_cents: int
    buying_power_cents: int | None
    positions_upserted: int
    positions_removed: int
    missing_from_broker: list[str]
    extra_on_broker: list[str]


def _sanitized_account(account: BrokerAccount) -> dict:
    """Snapshot-safe view of a broker account. Excludes account_id and full number."""
    return {
        "account_number_masked": account.account_number_masked,
        "status": account.status,
        "currency": account.currency,
        "cash_cents": account.cash_cents,
        "equity_cents": account.equity_cents,
        "buying_power_cents": account.buying_power_cents,
        "trading_blocked": account.trading_blocked,
        "account_blocked": account.account_blocked,
        "pattern_day_trader": account.pattern_day_trader,
    }


def reconcile(
    session: Session,
    *,
    broker: Broker,
    actor: str = "cron",
    now: datetime | None = None,
) -> ReconcileResult:
    """Snapshot the account, upsert positions, log diffs, and return a summary."""
    now = now or utcnow()

    account = broker.get_account()
    snapshot = PortfolioSnapshot(
        captured_at=now,
        cash_cents=account.cash_cents,
        equity_cents=account.equity_cents,
        buying_power_cents=account.buying_power_cents,
        raw_json=json.dumps(_sanitized_account(account)),
    )
    session.add(snapshot)

    # Local knowledge captured BEFORE upserting — the position table mirrors the
    # broker, so reading it after upsert would make "extra" detection vacuous.
    prior_position_symbols = {p.symbol for p in session.exec(select(Position)).all()}
    orders = session.exec(select(Order)).all()
    sent_buy_symbols = {o.symbol for o in orders if o.broker_order_id and o.side == "buy"}
    local_known = (
        prior_position_symbols
        | {o.symbol for o in orders}
        | {p.symbol for p in session.exec(select(Proposal)).all()}
    )

    broker_positions = broker.get_positions()
    broker_symbols = {p.symbol for p in broker_positions}
    positions_removed = 0
    for stale in session.exec(select(Position)).all():
        if stale.symbol not in broker_symbols:
            session.delete(stale)
            positions_removed += 1

    for bp in broker_positions:
        pos = session.get(Position, bp.symbol)
        if pos is None:
            pos = Position(symbol=bp.symbol, qty=bp.qty)
        pos.qty = bp.qty
        pos.avg_entry_price_cents = bp.avg_entry_price_cents
        pos.market_value_cents = bp.market_value_cents
        pos.updated_at = now
        session.add(pos)

    missing_from_broker = sorted(sent_buy_symbols - broker_symbols)
    extra_on_broker = sorted(broker_symbols - local_known)

    session.flush()  # assign snapshot.id

    log_event(
        session,
        actor=actor,
        action="reconcile",
        entity_type="portfolio_snapshot",
        entity_id=str(snapshot.id),
        decision="ok",
        details={
            "cash_cents": account.cash_cents,
            "equity_cents": account.equity_cents,
            "buying_power_cents": account.buying_power_cents,
            "positions_upserted": len(broker_positions),
            "positions_removed": positions_removed,
            "missing_from_broker": missing_from_broker,
            "extra_on_broker": extra_on_broker,
        },
    )

    return ReconcileResult(
        snapshot_id=snapshot.id,
        cash_cents=account.cash_cents,
        equity_cents=account.equity_cents,
        buying_power_cents=account.buying_power_cents,
        positions_upserted=len(broker_positions),
        positions_removed=positions_removed,
        missing_from_broker=missing_from_broker,
        extra_on_broker=extra_on_broker,
    )
