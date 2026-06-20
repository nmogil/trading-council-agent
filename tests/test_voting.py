import pytest

from trading_council.voting import APPROVED, PENDING, REJECTED, tally_votes

# Defaults from config/rules.yaml.
QUORUM = 60
MAJORITY = 50


def test_quorum_not_met_is_pending():
    # 1 of 5 members voted = 20% < 60%.
    result = tally_votes(5, yes=1, no=0, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.status == PENDING
    assert result.quorum_met is False


def test_yes_majority_with_quorum_is_approved():
    result = tally_votes(5, yes=3, no=1, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.status == APPROVED
    assert result.quorum_met is True


def test_tie_is_rejected():
    result = tally_votes(4, yes=2, no=2, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.status == REJECTED


def test_abstain_counts_toward_quorum():
    # 1 yes + 2 abstain of 5 = 60% participation -> quorum met, yes majority of decisive.
    result = tally_votes(5, yes=1, no=0, abstain=2, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.quorum_met is True
    assert result.status == APPROVED


def test_all_abstain_with_quorum_is_rejected():
    result = tally_votes(3, yes=0, no=0, abstain=3, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.quorum_met is True
    assert result.status == REJECTED


def test_no_majority_rejected():
    result = tally_votes(5, yes=1, no=2, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)
    assert result.status == REJECTED


def test_invalid_member_count_raises():
    with pytest.raises(ValueError):
        tally_votes(0, yes=0, no=0, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)


def test_negative_counts_raise():
    with pytest.raises(ValueError):
        tally_votes(5, yes=-1, no=0, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)



def test_invalid_percentages_raise():
    with pytest.raises(ValueError):
        tally_votes(5, yes=1, no=0, abstain=0, quorum_pct=101, majority_pct=MAJORITY)
    with pytest.raises(ValueError):
        tally_votes(5, yes=1, no=0, abstain=0, quorum_pct=QUORUM, majority_pct=-1)


def test_votes_cannot_exceed_active_members():
    with pytest.raises(ValueError):
        tally_votes(2, yes=2, no=1, abstain=0, quorum_pct=QUORUM, majority_pct=MAJORITY)
