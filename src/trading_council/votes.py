"""Voting service: record/change votes and close a proposal's vote.

A member may change their vote any time before the proposal closes (one row per
member per proposal, upserted). Closing tallies via :func:`voting.tally_votes` using
the rules' quorum/majority and the count of active members.

Deterministic close behavior:
- ``approved`` / ``rejected``  -> proposal status set accordingly.
- ``pending`` (quorum not met) -> proposal stays ``voting`` (re-runnable later).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from trading_council.audit import log_event
from trading_council.models import Member, Proposal, Vote, utcnow
from trading_council.rules import TradingRules, load_rules
from trading_council.voting import VoteResult, tally_votes

VALID_CHOICES = {"yes", "no", "abstain"}


def record_vote(
    session: Session,
    *,
    proposal_id: str,
    member_id: str,
    choice: str,
    now: datetime | None = None,
) -> Vote:
    """Record or update ``member_id``'s vote on a proposal that is open for voting."""
    now = now or utcnow()
    choice_n = (choice or "").strip().lower()
    if choice_n not in VALID_CHOICES:
        raise ValueError(f"invalid choice {choice!r}; must be yes, no, or abstain")

    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown proposal {proposal_id}")
    if proposal.status != "voting":
        raise ValueError(
            f"proposal {proposal_id} is not open for voting (status={proposal.status})"
        )

    member = session.get(Member, member_id)
    if member is None or not member.active:
        raise ValueError(f"unknown or inactive member {member_id}")

    vote = session.exec(
        select(Vote).where(Vote.proposal_id == proposal_id, Vote.member_id == member_id)
    ).first()
    if vote is not None:
        vote.choice = choice_n
        vote.created_at = now
    else:
        vote = Vote(proposal_id=proposal_id, member_id=member_id, choice=choice_n, created_at=now)
        session.add(vote)
    session.flush()

    log_event(
        session,
        actor=member_id,
        action="vote",
        entity_type="proposal",
        entity_id=proposal_id,
        decision=choice_n,
        details={"member_id": member_id, "choice": choice_n},
    )
    return vote


def close_vote(
    session: Session,
    *,
    proposal_id: str,
    rules: TradingRules | None = None,
    actor: str = "system",
    now: datetime | None = None,
) -> VoteResult:
    """Tally votes, update proposal status, and audit the result."""
    rules = rules or load_rules()
    now = now or utcnow()

    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown proposal {proposal_id}")
    if proposal.status != "voting":
        raise ValueError(
            f"proposal {proposal_id} is not open for voting (status={proposal.status})"
        )

    active_member_ids = {
        m.id for m in session.exec(select(Member).where(Member.active == True)).all()  # noqa: E712
    }
    active_members = len(active_member_ids)
    if active_members < 1:
        raise ValueError("cannot close vote with no active members")

    votes = [
        v
        for v in session.exec(select(Vote).where(Vote.proposal_id == proposal_id)).all()
        if v.member_id in active_member_ids
    ]
    yes = sum(1 for v in votes if v.choice == "yes")
    no = sum(1 for v in votes if v.choice == "no")
    abstain = sum(1 for v in votes if v.choice == "abstain")

    result = tally_votes(
        active_member_count=active_members,
        yes=yes,
        no=no,
        abstain=abstain,
        quorum_pct=rules.risk.quorum_pct,
        majority_pct=rules.risk.require_majority_pct,
    )

    if result.status in {"approved", "rejected"}:
        proposal.status = result.status
        session.add(proposal)
    # pending -> leave proposal in "voting" so it can be closed again later.
    session.flush()

    log_event(
        session,
        actor=actor,
        action="close_vote",
        entity_type="proposal",
        entity_id=proposal_id,
        decision=result.status,
        details={
            "yes": yes,
            "no": no,
            "abstain": abstain,
            "active_members": active_members,
            "quorum_met": result.quorum_met,
            "proposal_status": proposal.status,
        },
    )
    return result
