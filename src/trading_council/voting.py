"""Deterministic vote tallying.

Quorum is measured against participation (yes + no + abstain) — abstentions count
as participation by default. Majority is measured against decisive votes (yes + no)
so an abstaining member can establish quorum without tipping the outcome. A tie is a
rejection.
"""

from __future__ import annotations

from dataclasses import dataclass

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


@dataclass(frozen=True)
class VoteResult:
    status: str  # pending | approved | rejected
    quorum_met: bool
    participation: int
    yes: int
    no: int
    abstain: int


def tally_votes(
    active_member_count: int,
    yes: int,
    no: int,
    abstain: int,
    quorum_pct: int,
    majority_pct: int,
) -> VoteResult:
    if active_member_count < 1:
        raise ValueError("active_member_count must be >= 1")
    if min(yes, no, abstain) < 0:
        raise ValueError("vote counts must not be negative")
    if not 0 <= quorum_pct <= 100:
        raise ValueError("quorum_pct must be between 0 and 100")
    if not 0 <= majority_pct <= 100:
        raise ValueError("majority_pct must be between 0 and 100")

    participation = yes + no + abstain
    if participation > active_member_count:
        raise ValueError("vote counts cannot exceed active_member_count")

    # Integer-safe percentage comparisons (avoid float rounding).
    quorum_met = participation * 100 >= quorum_pct * active_member_count

    if not quorum_met:
        status = PENDING
    else:
        decisive = yes + no
        # Strict majority of decisive votes; ties (and all-abstain) reject.
        status = APPROVED if yes * 100 > majority_pct * decisive else REJECTED

    return VoteResult(
        status=status,
        quorum_met=quorum_met,
        participation=participation,
        yes=yes,
        no=no,
        abstain=abstain,
    )
