"""Deterministic pre-trade risk gate.

``evaluate_order`` is the single policy chokepoint between an approved proposal and
a broker order. It performs no broker calls and no DB writes — callers pass in the
portfolio state. It accumulates *all* applicable block reasons rather than failing on
the first, so a single decision explains everything wrong with an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_council.models import Proposal
from trading_council.rules import TradingRules


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: list[str]
    normalized_symbol: str | None = None


def evaluate_order(
    proposal: Proposal,
    *,
    rules: TradingRules,
    portfolio_equity_cents: int,
    existing_position_value_cents: int,
    trades_this_week: int,
    mode: str,
    live_approved: bool,
    kill_switch: bool,
) -> RiskDecision:
    symbol = rules.normalize_symbol(proposal.symbol)
    mode_normalized = mode.strip().lower()
    side_normalized = proposal.side.strip().lower()
    reasons: list[str] = []

    if kill_switch:
        reasons.append("kill switch engaged")

    if mode_normalized not in {"paper", "live"}:
        reasons.append(f"invalid mode {mode!r}")

    if mode_normalized == "live" and rules.execution.require_approval_for_live and not live_approved:
        reasons.append("live mode requires approval")

    if mode_normalized == "paper" and rules.execution.require_approval_for_paper and not live_approved:
        reasons.append("paper mode requires approval")

    if side_normalized not in {"buy", "sell"}:
        reasons.append(f"invalid side {proposal.side!r}")

    if not rules.is_allowed_symbol(symbol):
        reasons.append(f"symbol {symbol} not in allowlist")

    max_alloc = rules.risk.max_position_allocation_pct
    allocation_pct = Decimal(proposal.allocation_pct)
    if allocation_pct <= 0:
        reasons.append("allocation must be greater than 0%")
    if allocation_pct > max_alloc:
        reasons.append(f"allocation {allocation_pct}% exceeds max {max_alloc}%")

    if portfolio_equity_cents <= 0:
        reasons.append("portfolio equity must be greater than 0")
    if existing_position_value_cents < 0:
        reasons.append("existing position value must not be negative")
    if trades_this_week < 0:
        reasons.append("trades_this_week must not be negative")

    # Size the new order from equity; check both the order's notional cap and the
    # resulting combined position against the allocation cap.
    new_value_cents = int(portfolio_equity_cents * allocation_pct / 100)

    if new_value_cents > rules.risk.max_order_notional_cents:
        reasons.append(
            f"order notional {new_value_cents}c exceeds max "
            f"{rules.risk.max_order_notional_cents}c"
        )

    if side_normalized == "buy" and portfolio_equity_cents > 0:
        combined_cents = existing_position_value_cents + new_value_cents
        if combined_cents * 100 > max_alloc * portfolio_equity_cents:
            reasons.append(f"combined position in {symbol} exceeds max {max_alloc}%")

    if trades_this_week >= rules.risk.max_new_trades_per_week:
        reasons.append(
            f"already {trades_this_week} trade(s) this week; max "
            f"{rules.risk.max_new_trades_per_week}"
        )

    if side_normalized == "sell" and existing_position_value_cents <= 0:
        reasons.append(f"cannot sell {symbol}: no existing position")

    if (
        side_normalized == "sell"
        and not rules.risk.allow_shorting
        and existing_position_value_cents > 0
        and new_value_cents > existing_position_value_cents
    ):
        reasons.append(f"cannot sell {symbol}: order exceeds existing position and shorting is disabled")

    return RiskDecision(allowed=not reasons, reasons=reasons, normalized_symbol=symbol)
