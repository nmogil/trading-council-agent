"""Command-line interface for the Trading Council agent."""

from __future__ import annotations

import typer

from trading_council import db
from trading_council.broker.alpaca import AlpacaBroker
from trading_council.broker.base import BrokerCredentialsError
from trading_council.settings import Settings

app = typer.Typer(help="Trading Council agent operations")


@app.callback()
def main() -> None:
    """Trading Council agent operations.

    Defined so Typer keeps subcommands (e.g. ``status``) named even while only one
    command exists; future phases add more commands under this same app.
    """


@app.command()
def status() -> None:
    """Print a basic health line so cron/operators can confirm the CLI runs."""
    typer.echo("trading-council: ok")


@app.command(name="init-db")
def init_db() -> None:
    """Create all database tables using the configured database URL."""
    settings = Settings()
    db.init_db(settings.database_url)
    typer.echo(f"trading-council: database ready at {settings.database_url}")


@app.command(name="alpaca-account")
def alpaca_account() -> None:
    """Read-only Alpaca connectivity check: print account summary, never place orders."""
    settings = Settings()
    broker = AlpacaBroker(settings)
    try:
        account = broker.get_account()
    except BrokerCredentialsError as exc:
        typer.echo(f"trading-council: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    from trading_council.broker.base import cents_to_dollars

    typer.echo(f"mode:            {settings.mode}")
    typer.echo(f"account:         {account.account_number_masked}")
    typer.echo(f"status:          {account.status}")
    typer.echo(f"cash:            ${cents_to_dollars(account.cash_cents):.2f}")
    typer.echo(f"equity:          ${cents_to_dollars(account.equity_cents):.2f}")
    typer.echo(f"buying power:    ${cents_to_dollars(account.buying_power_cents):.2f}")
    typer.echo(f"trading blocked: {account.trading_blocked}")
    typer.echo(f"account blocked: {account.account_blocked}")


if __name__ == "__main__":  # pragma: no cover
    app()
