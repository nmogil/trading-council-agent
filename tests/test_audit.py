import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.audit import log_event
from trading_council.models import AuditLog


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def test_log_event_flushes_but_does_not_commit(session):
    entry = log_event(
        session,
        actor="cron",
        action="propose",
        entity_type="proposal",
        entity_id="2026-W26-A",
        decision="created",
        details={"symbol": "SPY"},
    )

    assert entry.id is not None  # flushed, so id assigned
    assert json.loads(entry.details_json) == {"symbol": "SPY"}

    session.rollback()  # not committed -> the row must disappear
    assert session.exec(select(AuditLog)).all() == []


def test_log_event_defaults_details_to_empty_object(session):
    entry = log_event(
        session,
        actor="system",
        action="boot",
        entity_type="service",
        entity_id="-",
    )
    assert json.loads(entry.details_json) == {}


def test_log_event_does_not_swallow_serialization_errors(session):
    with pytest.raises(TypeError):
        log_event(
            session,
            actor="x",
            action="a",
            entity_type="t",
            entity_id="1",
            details={"bad": object()},
        )
