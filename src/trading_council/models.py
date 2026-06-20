"""SQLModel tables for the trading council ledger.

Monetary values are stored as integer cents. Timestamps default to timezone-aware
UTC; tests may pass explicit datetimes. Explicit ``__tablename__`` values keep the
foreign-key references (e.g. ``proposal.id``) unambiguous.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as the default for created/captured timestamps."""
    return datetime.now(timezone.utc)


class Member(SQLModel, table=True):
    __tablename__ = "member"

    id: str = Field(primary_key=True)  # Discord user ID
    display_name: str
    contribution_cents: int = 5000
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Proposal(SQLModel, table=True):
    __tablename__ = "proposal"

    id: str = Field(primary_key=True)  # e.g. 2026-W26-A
    symbol: str
    side: str  # buy/sell
    allocation_pct: Decimal
    thesis: str
    risk: str
    exit_condition: str
    status: str = "draft"  # draft, voting, approved, rejected, executed, cancelled
    created_by: str
    created_at: datetime = Field(default_factory=utcnow)
    voting_closes_at: datetime | None = None


class Vote(SQLModel, table=True):
    __tablename__ = "vote"
    __table_args__ = (UniqueConstraint("proposal_id", "member_id"),)

    id: int | None = Field(default=None, primary_key=True)
    proposal_id: str = Field(foreign_key="proposal.id")
    member_id: str = Field(foreign_key="member.id")
    choice: str  # yes/no/abstain
    created_at: datetime = Field(default_factory=utcnow)


class Order(SQLModel, table=True):
    # "order" is a SQL reserved word; name the table trade_order to dodge quoting.
    __tablename__ = "trade_order"

    id: str = Field(primary_key=True)  # internal order ID
    proposal_id: str = Field(foreign_key="proposal.id", index=True, unique=True)
    broker: str = "alpaca"
    broker_order_id: str | None = None
    client_order_id: str = Field(index=True, unique=True)
    symbol: str
    side: str
    notional_cents: int
    status: str
    mode: str  # paper/live
    requested_at: datetime = Field(default_factory=utcnow)
    submitted_at: datetime | None = None
    raw_request_json: str
    raw_response_json: str | None = None


class Position(SQLModel, table=True):
    __tablename__ = "position"

    symbol: str = Field(primary_key=True)
    qty: Decimal
    avg_entry_price_cents: int | None = None
    market_value_cents: int | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class PortfolioSnapshot(SQLModel, table=True):
    __tablename__ = "portfolio_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    captured_at: datetime = Field(default_factory=utcnow)
    cash_cents: int
    equity_cents: int
    buying_power_cents: int | None = None
    raw_json: str


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    actor: str  # discord user, cron, system, agent
    action: str
    entity_type: str
    entity_id: str
    decision: str | None = None
    details_json: str
