"""Tests for the voting service. No network; in-memory SQLite."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from trading_council.models import AuditLog, Member, Proposal, Vote
from trading_council.votes import close_vote, record_vote

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        # Three active members; quorum (60%) needs >=2 participants.
        for i in range(1, 4):
            sess.add(Member(id=f"m{i}", display_name=f"Member {i}"))
        sess.add(Member(id="inactive", display_name="Gone", active=False))
        sess.add(
            Proposal(
                id="2026-W26-A",
                symbol="QQQ",
                side="buy",
                allocation_pct=Decimal("20"),
                thesis="t",
                risk="r",
                exit_condition="e",
                status="voting",
                created_by="noah",
            )
        )
        sess.commit()
        yield sess


def test_record_vote_and_change_before_close(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes", now=NOW)
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="no", now=NOW)
    votes = session.exec(select(Vote).where(Vote.member_id == "m1")).all()
    assert len(votes) == 1  # upserted, not duplicated
    assert votes[0].choice == "no"


def test_invalid_choice_fails(session):
    with pytest.raises(ValueError, match="invalid choice"):
        record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="maybe")


def test_unknown_or_inactive_member_fails(session):
    with pytest.raises(ValueError):
        record_vote(session, proposal_id="2026-W26-A", member_id="ghost", choice="yes")
    with pytest.raises(ValueError):
        record_vote(session, proposal_id="2026-W26-A", member_id="inactive", choice="yes")


def test_cannot_vote_on_closed_proposal(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m2", choice="yes")
    close_vote(session, proposal_id="2026-W26-A")
    with pytest.raises(ValueError, match="not open"):
        record_vote(session, proposal_id="2026-W26-A", member_id="m3", choice="yes")


def test_close_approved_with_quorum_and_majority(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m2", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m3", choice="no")
    result = close_vote(session, proposal_id="2026-W26-A")
    assert result.status == "approved"
    assert session.get(Proposal, "2026-W26-A").status == "approved"


def test_close_rejected_on_tie(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m2", choice="no")
    result = close_vote(session, proposal_id="2026-W26-A")
    assert result.status == "rejected"
    assert session.get(Proposal, "2026-W26-A").status == "rejected"


def test_close_pending_keeps_proposal_voting(session):
    # Only one participant -> quorum (60% of 3) not met.
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    result = close_vote(session, proposal_id="2026-W26-A")
    assert result.status == "pending"
    assert result.quorum_met is False
    assert session.get(Proposal, "2026-W26-A").status == "voting"


def test_close_writes_audit_with_tally(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m2", choice="yes")
    close_vote(session, proposal_id="2026-W26-A", actor="cli")
    log = session.exec(
        select(AuditLog).where(AuditLog.action == "close_vote")
    ).one()
    assert log.decision == "approved"
    assert '"yes": 2' in log.details_json



def test_close_excludes_votes_from_members_deactivated_before_close(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m2", choice="yes")
    record_vote(session, proposal_id="2026-W26-A", member_id="m3", choice="no")
    member = session.get(Member, "m3")
    member.active = False
    session.add(member)
    session.commit()

    result = close_vote(session, proposal_id="2026-W26-A")

    assert result.status == "approved"
    assert result.yes == 2
    assert result.no == 0
    assert session.get(Proposal, "2026-W26-A").status == "approved"


def test_close_with_no_active_members_fails_closed(session):
    record_vote(session, proposal_id="2026-W26-A", member_id="m1", choice="yes")
    for member in session.exec(select(Member)).all():
        member.active = False
        session.add(member)
    session.commit()

    with pytest.raises(ValueError, match="no active members"):
        close_vote(session, proposal_id="2026-W26-A")
