from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from trading_council.models import Member, Order, Position, Proposal, Vote


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    return eng


def _order(**overrides) -> Order:
    base = dict(
        id="o1",
        proposal_id="p1",
        client_order_id="c1",
        symbol="SPY",
        side="buy",
        notional_cents=1000,
        status="staged",
        mode="paper",
        raw_request_json="{}",
    )
    base.update(overrides)
    return Order(**base)


def test_tables_create_and_money_is_int_cents(engine):
    with Session(engine) as session:
        member = Member(id="1", display_name="Alice")
        session.add(member)
        session.commit()
        session.refresh(member)
        assert member.contribution_cents == 5000
        assert isinstance(member.contribution_cents, int)


def test_position_money_fields_are_int_cents(engine):
    with Session(engine) as session:
        position = Position(
            symbol="QQQ",
            qty=Decimal("1.5"),
            avg_entry_price_cents=48_025,
            market_value_cents=72_000,
        )
        session.add(position)
        session.commit()
        session.refresh(position)
        assert position.avg_entry_price_cents == 48_025
        assert position.market_value_cents == 72_000
        assert isinstance(position.avg_entry_price_cents, int)
        assert isinstance(position.market_value_cents, int)


def test_proposal_roundtrips_decimal_allocation(engine):
    with Session(engine) as session:
        session.add(
            Proposal(
                id="2026-W26-A",
                symbol="QQQ",
                side="buy",
                allocation_pct=Decimal("20"),
                thesis="t",
                risk="r",
                exit_condition="e",
                created_by="noah",
            )
        )
        session.commit()


def test_vote_unique_per_proposal_member(engine):
    with Session(engine) as session:
        session.add(Vote(proposal_id="p1", member_id="m1", choice="yes"))
        session.commit()
        session.add(Vote(proposal_id="p1", member_id="m1", choice="no"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_order_proposal_id_unique(engine):
    with Session(engine) as session:
        session.add(_order(id="o1", proposal_id="p1", client_order_id="c1"))
        session.commit()
        session.add(_order(id="o2", proposal_id="p1", client_order_id="c2"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_order_client_order_id_unique(engine):
    with Session(engine) as session:
        session.add(_order(id="o1", proposal_id="p1", client_order_id="c1"))
        session.commit()
        session.add(_order(id="o2", proposal_id="p2", client_order_id="c1"))
        with pytest.raises(IntegrityError):
            session.commit()
