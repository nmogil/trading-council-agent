"""Proposal creation service.

Validates a proposal against the trading rules *before* any DB write (fail closed),
assigns a human-friendly ``YYYY-Www-A/B/C`` id derived from the current ISO week and
the proposals already created that week, starts it in ``voting`` status, and records
an audit event. The clock is injectable so id generation is deterministic in tests.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from trading_council.audit import log_event
from trading_council.models import Proposal, utcnow
from trading_council.rules import TradingRules, load_rules

# Single-letter suffix per week; >26 proposals/week raises. Lift the cap
# (two-letter suffixes) only if a week ever genuinely needs more than 26 proposals.
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _week_prefix(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def next_proposal_id(session: Session, now: datetime) -> str:
    """Next ``YYYY-Www-X`` id for ``now``'s ISO week, lettered by existing count."""
    prefix = _week_prefix(now)
    existing = session.exec(select(Proposal).where(Proposal.id.like(f"{prefix}-%"))).all()
    n = len(existing)
    if n >= len(_LETTERS):
        raise ValueError(f"too many proposals for {prefix} this week (max {len(_LETTERS)})")
    return f"{prefix}-{_LETTERS[n]}"


def create_proposal(
    session: Session,
    *,
    symbol: str,
    side: str,
    allocation_pct: Decimal | int | float | str,
    thesis: str,
    risk: str,
    exit_condition: str,
    created_by: str,
    rules: TradingRules | None = None,
    now: datetime | None = None,
) -> Proposal:
    """Validate and persist a proposal, returning it. Raises ``ValueError`` on bad input."""
    rules = rules or load_rules()
    now = now or utcnow()

    symbol_n = rules.normalize_symbol(symbol)
    side_n = (side or "").strip().lower()

    if not rules.is_allowed_symbol(symbol_n):
        raise ValueError(f"symbol {symbol_n} not in allowlist")
    if side_n not in {"buy", "sell"}:
        raise ValueError(f"invalid side {side!r}; must be buy or sell")

    try:
        alloc = Decimal(str(allocation_pct))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid allocation_pct {allocation_pct!r}") from exc
    if alloc <= 0 or alloc > 100:
        raise ValueError("allocation_pct must be between 0 and 100")
    if alloc > rules.risk.max_position_allocation_pct:
        raise ValueError(
            "allocation_pct exceeds max position allocation "
            f"{rules.risk.max_position_allocation_pct}%"
        )

    for name, value in (
        ("thesis", thesis),
        ("risk", risk),
        ("exit_condition", exit_condition),
        ("created_by", created_by),
    ):
        if not value or not str(value).strip():
            raise ValueError(f"{name} must not be empty")

    proposal_id = next_proposal_id(session, now)
    proposal = Proposal(
        id=proposal_id,
        symbol=symbol_n,
        side=side_n,
        allocation_pct=alloc,
        thesis=thesis,
        risk=risk,
        exit_condition=exit_condition,
        status="voting",
        created_by=created_by,
        created_at=now,
    )
    session.add(proposal)
    session.flush()

    log_event(
        session,
        actor=created_by,
        action="propose",
        entity_type="proposal",
        entity_id=proposal_id,
        decision="voting",
        details={"symbol": symbol_n, "side": side_n, "allocation_pct": str(alloc)},
    )
    return proposal
