from decimal import Decimal

import pytest

from trading_council.models import Proposal
from trading_council.risk import evaluate_order
from trading_council.rules import load_rules


@pytest.fixture
def rules():
    return load_rules()


def _proposal(**overrides) -> Proposal:
    base = dict(
        id="2026-W26-A",
        symbol="SPY",
        side="buy",
        allocation_pct=Decimal("20"),
        thesis="t",
        risk="r",
        exit_condition="e",
        created_by="noah",
    )
    base.update(overrides)
    return Proposal(**base)


def _evaluate(rules, proposal, **overrides):
    kwargs = dict(
        rules=rules,
        portfolio_equity_cents=20_000,
        existing_position_value_cents=0,
        trades_this_week=0,
        mode="paper",
        live_approved=False,
        kill_switch=False,
    )
    kwargs.update(overrides)
    return evaluate_order(proposal, **kwargs)


def test_clean_order_allowed(rules):
    decision = _evaluate(rules, _proposal())
    assert decision.allowed is True
    assert decision.reasons == []
    assert decision.normalized_symbol == "SPY"


def test_symbol_normalized_to_uppercase(rules):
    decision = _evaluate(rules, _proposal(symbol="spy"))
    assert decision.allowed is True
    assert decision.normalized_symbol == "SPY"


def test_kill_switch_blocks_everything(rules):
    decision = _evaluate(rules, _proposal(), kill_switch=True)
    assert decision.allowed is False
    assert any("kill switch" in r for r in decision.reasons)


def test_live_without_approval_blocks(rules):
    decision = _evaluate(rules, _proposal(), mode="live", live_approved=False)
    assert decision.allowed is False
    assert any("live mode requires approval" in r for r in decision.reasons)


def test_live_with_approval_allowed(rules):
    decision = _evaluate(rules, _proposal(), mode="live", live_approved=True)
    assert decision.allowed is True


def test_symbol_not_in_allowlist_blocks(rules):
    decision = _evaluate(rules, _proposal(symbol="FOO"))
    assert decision.allowed is False
    assert any("allowlist" in r for r in decision.reasons)


def test_allocation_above_max_blocks(rules):
    decision = _evaluate(rules, _proposal(allocation_pct=Decimal("30")))
    assert decision.allowed is False
    assert any("allocation" in r for r in decision.reasons)


def test_existing_plus_new_above_max_blocks(rules):
    # 20% new (4000c) + 2000c existing = 6000c of 20000c equity = 30% > 25%.
    decision = _evaluate(rules, _proposal(), existing_position_value_cents=2_000)
    assert decision.allowed is False
    assert any("combined position" in r for r in decision.reasons)


def test_more_than_one_trade_this_week_blocks(rules):
    decision = _evaluate(rules, _proposal(), trades_this_week=1)
    assert decision.allowed is False
    assert any("this week" in r for r in decision.reasons)


def test_sell_non_held_blocks(rules):
    decision = _evaluate(rules, _proposal(side="sell"), existing_position_value_cents=0)
    assert decision.allowed is False
    assert any("no existing position" in r for r in decision.reasons)


def test_sell_held_allowed(rules):
    # Hold 1000c, sell with small allocation so combined stays under cap.
    decision = _evaluate(
        rules,
        _proposal(side="sell", allocation_pct=Decimal("5")),
        existing_position_value_cents=1_000,
    )
    assert decision.allowed is True


def test_order_notional_cap_blocks(rules):
    # 25% of 100_000c = 25_000c > 5_000c notional cap.
    decision = _evaluate(
        rules,
        _proposal(allocation_pct=Decimal("25")),
        portfolio_equity_cents=100_000,
    )
    assert decision.allowed is False
    assert any("notional" in r for r in decision.reasons)


def test_multiple_reasons_accumulate(rules):
    decision = _evaluate(
        rules,
        _proposal(symbol="FOO", allocation_pct=Decimal("30")),
        kill_switch=True,
    )
    assert decision.allowed is False
    assert len(decision.reasons) >= 3



def test_live_mode_normalizes_before_approval_check(rules):
    decision = _evaluate(rules, _proposal(), mode=" LIVE ", live_approved=False)
    assert decision.allowed is False
    assert any("live mode requires approval" in r for r in decision.reasons)


def test_invalid_mode_blocks(rules):
    decision = _evaluate(rules, _proposal(), mode="demo")
    assert decision.allowed is False
    assert any("invalid mode" in r for r in decision.reasons)


def test_sell_side_normalizes_before_position_check(rules):
    decision = _evaluate(rules, _proposal(side=" Sell "), existing_position_value_cents=0)
    assert decision.allowed is False
    assert any("no existing position" in r for r in decision.reasons)


def test_invalid_side_blocks(rules):
    decision = _evaluate(rules, _proposal(side="hold"))
    assert decision.allowed is False
    assert any("invalid side" in r for r in decision.reasons)


def test_negative_allocation_blocks(rules):
    decision = _evaluate(rules, _proposal(allocation_pct=Decimal("-10")))
    assert decision.allowed is False
    assert any("allocation must be greater" in r for r in decision.reasons)


def test_zero_or_negative_portfolio_equity_blocks(rules):
    decision = _evaluate(rules, _proposal(), portfolio_equity_cents=0)
    assert decision.allowed is False
    assert any("portfolio equity" in r for r in decision.reasons)


def test_negative_state_inputs_block(rules):
    decision = _evaluate(
        rules,
        _proposal(),
        existing_position_value_cents=-1,
        trades_this_week=-1,
    )
    assert decision.allowed is False
    assert any("existing position" in r for r in decision.reasons)
    assert any("trades_this_week" in r for r in decision.reasons)



def test_sell_larger_than_position_blocks_when_shorting_disabled(rules):
    # 5% of 20_000c equity is a 1_000c sell, larger than a 200c held position.
    decision = _evaluate(
        rules,
        _proposal(side="sell", allocation_pct=Decimal("5")),
        existing_position_value_cents=200,
    )
    assert decision.allowed is False
    assert any("shorting is disabled" in r for r in decision.reasons)


def test_sell_within_position_allowed_when_shorting_disabled(rules):
    # 5% of 20_000c equity is a 1_000c sell, exactly covered by the held position.
    decision = _evaluate(
        rules,
        _proposal(side="sell", allocation_pct=Decimal("5")),
        existing_position_value_cents=1_000,
    )
    assert decision.allowed is True



def test_sell_reduces_exposure_even_when_existing_position_at_max(rules):
    # Existing position is 25% of equity; selling 5% should reduce exposure, not be
    # treated like a buy that increases combined allocation.
    decision = _evaluate(
        rules,
        _proposal(side="sell", allocation_pct=Decimal("5")),
        existing_position_value_cents=5_000,
    )
    assert decision.allowed is True
