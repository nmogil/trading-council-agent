"""Tests for the proposal creation service. No network; in-memory SQLite."""

import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.models import AuditLog, Proposal
from trading_council.proposals import create_proposal

# 2026-06-22 is a Monday in ISO week 26 -> ids start "2026-W26-...".
NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _create(session, **overrides):
    base = dict(
        symbol="QQQ",
        side="buy",
        allocation_pct=Decimal("20"),
        thesis="momentum",
        risk="drawdown",
        exit_condition="stop at -8%",
        created_by="noah",
        now=NOW,
    )
    base.update(overrides)
    return create_proposal(session, **base)


def test_create_proposal_sets_voting_status_and_normalizes_symbol(session):
    proposal = _create(session, symbol="qqq")
    assert proposal.status == "voting"
    assert proposal.symbol == "QQQ"
    assert proposal.side == "buy"
    assert session.get(Proposal, proposal.id) is not None


def test_proposal_id_format_and_weekly_sequence(session):
    a = _create(session)
    b = _create(session)
    c = _create(session)
    assert re.fullmatch(r"\d{4}-W\d{2}-A", a.id)
    assert a.id.endswith("-A")
    assert b.id.endswith("-B")
    assert c.id.endswith("-C")
    assert a.id[:-1] == b.id[:-1] == c.id[:-1]


def test_create_proposal_writes_audit_event(session):
    proposal = _create(session)
    log = session.exec(select(AuditLog).where(AuditLog.entity_id == proposal.id)).one()
    assert log.action == "propose"
    assert log.decision == "voting"


def test_unknown_symbol_fails_before_insert(session):
    with pytest.raises(ValueError, match="allowlist"):
        _create(session, symbol="FOO")
    assert session.exec(select(Proposal)).all() == []


@pytest.mark.parametrize(
    "overrides",
    [
        dict(side="hold"),
        dict(allocation_pct=Decimal("0")),
        dict(allocation_pct=Decimal("30")),
        dict(allocation_pct=Decimal("150")),
        dict(allocation_pct="abc"),
        dict(thesis="  "),
        dict(created_by=""),
    ],
)
def test_invalid_fields_fail_closed(session, overrides):
    with pytest.raises(ValueError):
        _create(session, **overrides)
    assert session.exec(select(Proposal)).all() == []
