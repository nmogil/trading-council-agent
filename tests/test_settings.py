import pytest
from pydantic import ValidationError

from trading_council.settings import Settings

# Env vars that influence mode/safety validation; cleared before each test so a
# polluted shell environment cannot make these assertions pass or fail spuriously.
MANAGED_ENV = [
    "TRADING_COUNCIL_MODE",
    "TRADING_COUNCIL_LIVE_ENABLED",
    "TRADING_COUNCIL_KILL_SWITCH",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in MANAGED_ENV:
        monkeypatch.delenv(var, raising=False)


def test_defaults_to_paper_mode() -> None:
    settings = Settings(_env_file=None)
    assert settings.mode == "paper"
    assert settings.live_enabled is False
    assert settings.kill_switch is False


def test_live_mode_without_enable_flag_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_COUNCIL_MODE", "live")
    with pytest.raises(ValidationError, match="TRADING_COUNCIL_LIVE_ENABLED"):
        Settings(_env_file=None)


def test_live_mode_with_enable_flag_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_COUNCIL_MODE", "live")
    monkeypatch.setenv("TRADING_COUNCIL_LIVE_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.mode == "live"
    assert settings.live_enabled is True


def test_invalid_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_COUNCIL_MODE", "demo")
    with pytest.raises(ValidationError, match="paper or live"):
        Settings(_env_file=None)


def test_kill_switch_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_COUNCIL_KILL_SWITCH", "true")
    settings = Settings(_env_file=None)
    assert settings.kill_switch is True
