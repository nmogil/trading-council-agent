from typer.testing import CliRunner

from trading_council.cli import app


def test_status_command() -> None:
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0
    assert "trading-council: ok" in result.stdout
