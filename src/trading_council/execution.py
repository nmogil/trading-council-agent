"""Execution: stage an approved proposal into an order, then submit it (paper only).

Two steps, both fail closed:

``stage_order_for_proposal`` turns an *approved* proposal into a ``staged`` order
after sizing notional from the latest portfolio equity and running the risk gate.

``submit_order_for_proposal`` submits a staged order through the narrow broker
interface in **paper mode only**. Live submission is not enabled in this phase and
raises. The broker is called with a stable ``client_order_id`` for idempotency;
re-running on an already-submitted order returns it without placing a second order.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from trading_council.audit import log_event
from trading_council.broker.base import Broker, BrokerOrder
from trading_council.models import Order, PortfolioSnapshot, Position, Proposal, utcnow
from trading_council.risk import evaluate_order
from trading_council.rules import TradingRules, load_rules
from trading_council.settings import Settings


class ExecutionError(RuntimeError):
    """Raised when staging/submission preconditions are not met."""


class RiskRejected(ExecutionError):
    """Raised when the risk gate blocks an order. ``reasons`` lists every block."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _client_order_id(proposal_id: str) -> str:
    """Stable idempotency key derived from the proposal id (one order per proposal)."""
    return f"tc-{proposal_id}"


def _latest_equity_cents(session: Session) -> int:
    snap = session.exec(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.captured_at.desc())
    ).first()
    if snap is None:
        raise ExecutionError("no portfolio snapshot available; run reconcile first")
    return snap.equity_cents


def _existing_position_value_cents(session: Session, symbol: str) -> int:
    pos = session.get(Position, symbol)
    if pos is None or pos.market_value_cents is None:
        return 0
    return pos.market_value_cents


def _trades_this_week(session: Session, now: datetime, *, exclude_proposal_id: str | None) -> int:
    iso = now.isocalendar()
    count = 0
    for order in session.exec(select(Order)).all():
        if order.proposal_id == exclude_proposal_id:
            continue
        if order.status == "rejected":
            continue
        oi = order.requested_at.isocalendar()
        if (oi.year, oi.week) == (iso.year, iso.week):
            count += 1
    return count


def _sanitize_broker_order(order: BrokerOrder) -> dict:
    """JSON-safe view of a broker order. ``BrokerOrder`` holds no secrets by design."""
    data = asdict(order)
    for key, value in data.items():
        if isinstance(value, Decimal):
            data[key] = str(value)
    return data


def stage_order_for_proposal(
    session: Session,
    proposal_id: str,
    actor: str,
    *,
    rules: TradingRules | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Order:
    """Create a ``staged`` order for an approved proposal after the risk gate passes."""
    rules = rules or load_rules()
    settings = settings or Settings()
    now = now or utcnow()

    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise ExecutionError(f"unknown proposal {proposal_id}")
    if proposal.status != "approved":
        raise ExecutionError(
            f"proposal {proposal_id} is not approved (status={proposal.status})"
        )

    existing = session.exec(select(Order).where(Order.proposal_id == proposal_id)).first()
    if existing is not None:
        raise ExecutionError(f"order already exists for proposal {proposal_id}")

    symbol = rules.normalize_symbol(proposal.symbol)
    equity_cents = _latest_equity_cents(session)
    existing_value_cents = _existing_position_value_cents(session, symbol)
    trades = _trades_this_week(session, now, exclude_proposal_id=None)

    decision = evaluate_order(
        proposal,
        rules=rules,
        portfolio_equity_cents=equity_cents,
        existing_position_value_cents=existing_value_cents,
        trades_this_week=trades,
        mode=settings.mode,
        live_approved=False,
        kill_switch=settings.kill_switch,
    )
    if not decision.allowed:
        log_event(
            session,
            actor=actor,
            action="stage_order",
            entity_type="proposal",
            entity_id=proposal_id,
            decision="rejected",
            details={"reasons": decision.reasons},
        )
        raise RiskRejected(decision.reasons)

    notional_cents = int(equity_cents * Decimal(proposal.allocation_pct) / 100)
    side = proposal.side.strip().lower()
    coid = _client_order_id(proposal_id)
    raw_request = {
        "symbol": symbol,
        "side": side,
        "notional_cents": notional_cents,
        "client_order_id": coid,
        "mode": settings.mode,
    }
    order = Order(
        id=coid,
        proposal_id=proposal_id,
        broker="alpaca",
        client_order_id=coid,
        symbol=symbol,
        side=side,
        notional_cents=notional_cents,
        status="staged",
        mode=settings.mode,
        requested_at=now,
        raw_request_json=json.dumps(raw_request),
    )
    session.add(order)
    session.flush()

    log_event(
        session,
        actor=actor,
        action="stage_order",
        entity_type="order",
        entity_id=coid,
        decision="staged",
        details={
            "proposal_id": proposal_id,
            "symbol": symbol,
            "side": side,
            "notional_cents": notional_cents,
            "risk_reasons": decision.reasons,
        },
    )
    return order


def submit_order_for_proposal(
    session: Session,
    proposal_id: str,
    actor: str,
    *,
    broker: Broker | None = None,
    rules: TradingRules | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> Order:
    """Submit a staged order to the broker (paper only). Idempotent per proposal."""
    rules = rules or load_rules()
    settings = settings or Settings()
    now = now or utcnow()

    order = session.exec(select(Order).where(Order.proposal_id == proposal_id)).first()
    if order is None:
        raise ExecutionError(f"no staged order for proposal {proposal_id}; stage it first")
    if order.status != "staged":
        # Already submitted (or beyond): do not place a second broker order.
        return order

    # Paper only this phase. Live must fail closed — no approval bypass exists here.
    if settings.mode != "paper":
        raise ExecutionError("live order submission is not enabled in this phase; paper mode only")

    proposal = session.get(Proposal, proposal_id)
    if proposal is None:  # pragma: no cover - order implies proposal via FK
        raise ExecutionError(f"unknown proposal {proposal_id}")
    if proposal.status != "approved":
        raise ExecutionError(
            f"proposal {proposal_id} is not approved (status={proposal.status})"
        )

    # Re-run the risk gate at submit time (kill switch may have flipped since staging).
    # Exclude this proposal's own order from the weekly trade count.
    equity_cents = _latest_equity_cents(session)
    existing_value_cents = _existing_position_value_cents(session, order.symbol)
    trades = _trades_this_week(session, now, exclude_proposal_id=proposal_id)
    current_notional_cents = int(equity_cents * Decimal(proposal.allocation_pct) / 100)
    if current_notional_cents != order.notional_cents:
        raise ExecutionError(
            "staged order notional is stale; restage before submitting "
            f"(staged={order.notional_cents}c current={current_notional_cents}c)"
        )
    decision = evaluate_order(
        proposal,
        rules=rules,
        portfolio_equity_cents=equity_cents,
        existing_position_value_cents=existing_value_cents,
        trades_this_week=trades,
        mode=settings.mode,
        live_approved=False,
        kill_switch=settings.kill_switch,
    )
    if not decision.allowed:
        log_event(
            session,
            actor=actor,
            action="submit_order",
            entity_type="order",
            entity_id=order.id,
            decision="rejected",
            details={"proposal_id": proposal_id, "reasons": decision.reasons},
        )
        raise RiskRejected(decision.reasons)

    if broker is None:
        from trading_council.broker.alpaca import AlpacaBroker

        broker = AlpacaBroker(settings)

    broker_order = broker.place_market_order(
        symbol=order.symbol,
        side=order.side,  # type: ignore[arg-type]
        notional_cents=order.notional_cents,
        client_order_id=order.client_order_id,
    )

    order.broker_order_id = broker_order.broker_order_id
    order.status = broker_order.status or "submitted"
    order.submitted_at = now
    order.raw_response_json = json.dumps(_sanitize_broker_order(broker_order))
    session.add(order)
    session.flush()

    log_event(
        session,
        actor=actor,
        action="submit_order",
        entity_type="order",
        entity_id=order.id,
        decision=order.status,
        details={
            "proposal_id": proposal_id,
            "broker_order_id": order.broker_order_id,
            "status": order.status,
            "notional_cents": order.notional_cents,
            "risk_allowed": decision.allowed,
        },
    )
    return order
