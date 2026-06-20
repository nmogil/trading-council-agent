import pytest
import yaml

from trading_council.rules import TradingRules, load_rules


def test_loads_real_config():
    rules = load_rules()
    assert rules.version == 1
    assert "SPY" in rules.universe.allowed_symbols
    assert rules.risk.max_position_allocation_pct == 25
    assert rules.execution.require_approval_for_live is True
    assert rules.execution.require_approval_for_paper is False


def _valid_config() -> dict:
    return {
        "version": 1,
        "universe": {"allowed_symbols": ["spy", "QQQ"]},
        "risk": {
            "max_position_allocation_pct": 25,
            "max_new_trades_per_week": 1,
            "max_order_notional_cents": 5000,
            "quorum_pct": 60,
            "require_majority_pct": 50,
        },
        "execution": {},
    }


def _write(tmp_path, config):
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_path_override_and_symbol_normalization(tmp_path):
    rules = load_rules(_write(tmp_path, _valid_config()))
    assert rules.universe.allowed_symbols == ["SPY", "QQQ"]
    assert rules.is_allowed_symbol("spy") is True
    assert rules.is_allowed_symbol("aapl") is False


def test_empty_symbols_fail(tmp_path):
    config = _valid_config()
    config["universe"]["allowed_symbols"] = []
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_blank_symbol_fails(tmp_path):
    config = _valid_config()
    config["universe"]["allowed_symbols"] = ["SPY", "  "]
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_invalid_percentage_fails(tmp_path):
    config = _valid_config()
    config["risk"]["max_position_allocation_pct"] = 150
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_negative_money_fails(tmp_path):
    config = _valid_config()
    config["risk"]["max_order_notional_cents"] = -1
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_negative_weekly_count_fails(tmp_path):
    config = _valid_config()
    config["risk"]["max_new_trades_per_week"] = -1
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_non_mapping_fails(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        load_rules(path)


def test_model_validate_directly():
    rules = TradingRules.model_validate(_valid_config())
    assert rules.normalize_symbol(" tsla ") == "TSLA"



def test_duplicate_symbols_fail(tmp_path):
    config = _valid_config()
    config["universe"]["allowed_symbols"] = ["SPY", "spy"]
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_unknown_top_level_key_fails(tmp_path):
    config = _valid_config()
    config["typo"] = True
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))


def test_unknown_nested_key_fails(tmp_path):
    config = _valid_config()
    config["risk"]["allow_margin_typo"] = True
    with pytest.raises(ValueError):
        load_rules(_write(tmp_path, config))
