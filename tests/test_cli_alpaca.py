"""CLI tests for `alpaca-account`. No network: success path uses a fake broker."""

from typer.testing import CliRunner

from trading_council import cli
from trading_council.broker.base import BrokerAccount

runner = CliRunner()


def _clear_paper_creds(monkeypatch):
    # Empty (not just unset) so a stray real env var can't leak in.
    monkeypatch.setenv("TRADING_COUNCIL_MODE", "paper")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "")


def test_alpaca_account_missing_credentials_fails_cleanly(monkeypatch):
    _clear_paper_creds(monkeypatch)
    result = runner.invoke(cli.app, ["alpaca-account"])
    assert result.exit_code == 1
    assert "missing Alpaca paper credentials" in result.output
    # No secrets / key values echoed.
    assert "SECRET" not in result.output.upper().replace("ALPACA_*_SECRET_KEY", "")


class _FakeBroker:
    def __init__(self, settings, **_kwargs):
        self.settings = settings

    def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            account_id="acct-1",
            account_number_masked="****4321",
            status="ACTIVE",
            currency="USD",
            cash_cents=100_050,
            equity_cents=200_000,
            buying_power_cents=300_000,
            trading_blocked=False,
            account_blocked=False,
            pattern_day_trader=False,
        )


def test_alpaca_account_prints_summary_without_secrets(monkeypatch):
    monkeypatch.setenv("TRADING_COUNCIL_MODE", "paper")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "paper-secret")
    monkeypatch.setattr(cli, "AlpacaBroker", _FakeBroker)

    result = runner.invoke(cli.app, ["alpaca-account"])
    assert result.exit_code == 0
    assert "mode:" in result.output and "paper" in result.output
    assert "****4321" in result.output
    assert "$1000.50" in result.output
    assert "$2000.00" in result.output
    assert "trading blocked: False" in result.output
    # Never leak the secret or full account number.
    assert "paper-secret" not in result.output
    assert "paper-key" not in result.output
