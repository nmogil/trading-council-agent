"""Command-line interface for the Trading Council agent."""

from __future__ import annotations

import typer

from trading_council import db
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


if __name__ == "__main__":  # pragma: no cover
    app()
