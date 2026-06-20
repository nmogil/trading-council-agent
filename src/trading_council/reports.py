"""Human-readable portfolio and weekly-recap text for CLI (and future Discord use).

Pure read/render functions over the ledger. Output is plain bullets (no markdown
tables) so it stays terminal- and test-friendly. ``now`` is injectable so week
boundaries and "latest" selection are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlmodel import Session, select

from trading_council.broker.base import cents_to_dollars
from trading_council.models import AuditLog, Order, PortfolioSnapshot, Position, Proposal, utcnow
from trading_council.settings import Settings


def _dollars(cents: int | None) -> str:
    return "n/a" if cents is None else f"${cents_to_dollars(cents):.2f}"


def _num(value: Decimal) -> str:
    """Trim trailing zeros for display (SQLite pads Decimals, e.g. 3.0000000000)."""
    return format(Decimal(value).normalize(), "f")


def _latest_snapshot(session: Session) -> PortfolioSnapshot | None:
    return session.exec(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.captured_at.desc())
    ).first()


def _naive_utc(dt: datetime) -> datetime:
    """Drop tzinfo (assuming UTC). SQLite stores datetimes naive, so all comparisons
    happen in naive-UTC space to avoid offset-naive/aware TypeErrors."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 (start, inclusive) and the next Monday (end, exclusive), naive UTC."""
    base = _naive_utc(now)
    start = (base - timedelta(days=base.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def portfolio_summary(
    session: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Render latest equity/cash/buying power, positions, and open proposals."""
    settings = settings or Settings()
    lines = [f"Trading Council Portfolio — {settings.mode}"]

    snap = _latest_snapshot(session)
    if snap is None:
        lines.append("No portfolio snapshot yet — run `trading-council reconcile`.")
    else:
        lines.append(f"Equity: {_dollars(snap.equity_cents)}")
        lines.append(f"Cash: {_dollars(snap.cash_cents)}")
        lines.append(f"Buying power: {_dollars(snap.buying_power_cents)}")

    positions = session.exec(select(Position).order_by(Position.symbol)).all()
    lines.append("Positions:")
    if not positions:
        lines.append("- none")
    else:
        for p in positions:
            lines.append(
                f"- {p.symbol}: qty {_num(p.qty)}, market value {_dollars(p.market_value_cents)}"
            )

    open_proposals = session.exec(
        select(Proposal).where(Proposal.status == "voting").order_by(Proposal.id)
    ).all()
    lines.append("Open proposals:")
    if not open_proposals:
        lines.append("- none")
    else:
        for prop in open_proposals:
            lines.append(
                f"- {prop.id}: {prop.symbol} {prop.side} {_num(prop.allocation_pct)}%"
            )

    return "\n".join(lines)


def weekly_recap(
    session: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Render the current ISO week's equity move, trades, and governance outcomes."""
    settings = settings or Settings()
    now = now or utcnow()
    start, end = _week_bounds(now)

    lines = [
        f"Trading Council Weekly Recap — {settings.mode}",
        f"Week: {start.date()} to {(end - timedelta(days=1)).date()}",
    ]

    week_snaps = session.exec(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.captured_at >= start)
        .where(PortfolioSnapshot.captured_at < end)
        .order_by(PortfolioSnapshot.captured_at)
    ).all()
    if week_snaps:
        begin, finish = week_snaps[0], week_snaps[-1]
        lines.append(f"Beginning equity: {_dollars(begin.equity_cents)}")
        lines.append(f"Ending equity: {_dollars(finish.equity_cents)}")
        lines.append(f"Change: {_dollars(finish.equity_cents - begin.equity_cents)}")
    else:
        lines.append("Equity: no snapshots this week.")

    orders = session.exec(select(Order)).all()
    week_orders = [
        o
        for o in orders
        if o.submitted_at is not None
        and start <= _naive_utc(o.submitted_at) < end
        and o.status != "rejected"
    ]
    lines.append(f"Trades executed/submitted: {len(week_orders)}")
    for o in sorted(week_orders, key=lambda o: o.id):
        lines.append(f"- {o.symbol} {o.side} {_dollars(o.notional_cents)} ({o.status})")

    close_logs = session.exec(
        select(AuditLog).where(AuditLog.action == "close_vote")
    ).all()
    week_close_logs = [
        log for log in close_logs if start <= _naive_utc(log.created_at) < end
    ]
    accepted = sum(1 for log in week_close_logs if log.decision == "approved")
    rejected = sum(1 for log in week_close_logs if log.decision == "rejected")
    lines.append(f"Proposals accepted: {accepted}")
    lines.append(f"Proposals rejected: {rejected}")

    lines.append("Reminder: paper mode results are not real P/L.")
    return "\n".join(lines)
