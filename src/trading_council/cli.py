"""Command-line interface for the Trading Council agent."""

from __future__ import annotations

from decimal import Decimal

import typer
from sqlmodel import select

from trading_council import db
from trading_council.broker.alpaca import AlpacaBroker
from trading_council.broker.base import BrokerCredentialsError
from trading_council.execution import (
    ExecutionError,
    stage_order_for_proposal,
    submit_order_for_proposal,
)
from trading_council.models import Order
from trading_council.proposals import create_proposal
from trading_council.settings import Settings
from trading_council.votes import close_vote, record_vote

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


@app.command()
def propose(
    symbol: str = typer.Option(..., "--symbol"),
    side: str = typer.Option(..., "--side"),
    allocation_pct: float = typer.Option(..., "--allocation-pct"),
    thesis: str = typer.Option(..., "--thesis"),
    risk: str = typer.Option(..., "--risk"),
    exit_condition: str = typer.Option(..., "--exit-condition"),
    created_by: str = typer.Option(..., "--created-by"),
) -> None:
    """Create a proposal (status ``voting``) after validating it against the rules."""
    settings = Settings()
    engine = db.init_db(settings.database_url)
    with db.get_session(engine) as session:
        try:
            proposal = create_proposal(
                session,
                symbol=symbol,
                side=side,
                allocation_pct=Decimal(str(allocation_pct)),
                thesis=thesis,
                risk=risk,
                exit_condition=exit_condition,
                created_by=created_by,
            )
        except ValueError as exc:
            typer.echo(f"trading-council: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
        typer.echo(
            f"created proposal {proposal.id} "
            f"({proposal.symbol} {proposal.side} {proposal.allocation_pct}%) "
            f"status={proposal.status}"
        )


@app.command()
def research(
    symbol: str = typer.Argument(...),
    propose: bool = typer.Option(False, "--propose", help="Create a proposal from the brief"),
    side: str = typer.Option("", "--side", help="buy/sell; defaults to the brief's suggestion"),
    allocation_pct: float = typer.Option(
        0.0, "--allocation-pct", help="defaults to the brief's suggestion"
    ),
    created_by: str = typer.Option("research-agent", "--created-by"),
) -> None:
    """Research a symbol with the LLM agent; optionally open a proposal from the brief."""
    from trading_council.research import format_brief, research as run_research

    settings = Settings()
    try:
        brief = run_research(symbol, settings)
    except Exception as exc:  # noqa: BLE001  surface any agent/API failure cleanly
        typer.echo(f"trading-council: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(format_brief(brief))
    if not propose:
        return

    final_side = side or brief.suggested_side
    final_alloc = allocation_pct or brief.suggested_allocation_pct
    if final_side == "none":
        typer.echo("trading-council: brief suggests no trade; pass --side to override", err=True)
        raise typer.Exit(code=1)

    engine = db.init_db(settings.database_url)
    with db.get_session(engine) as session:
        try:
            proposal = create_proposal(
                session,
                symbol=brief.symbol,
                side=final_side,
                allocation_pct=Decimal(str(final_alloc)),
                thesis=brief.thesis,
                risk=brief.risk,
                exit_condition=brief.exit_condition,
                created_by=created_by,
            )
        except ValueError as exc:
            typer.echo(f"trading-council: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
        typer.echo(f"created proposal {proposal.id} from brief, status={proposal.status}")


@app.command()
def vote(
    proposal_id: str = typer.Argument(...),
    member_id: str = typer.Option(..., "--member-id"),
    choice: str = typer.Option(..., "--choice"),
) -> None:
    """Record or change a member's vote on an open proposal."""
    settings = Settings()
    engine = db.init_db(settings.database_url)
    with db.get_session(engine) as session:
        try:
            recorded = record_vote(
                session, proposal_id=proposal_id, member_id=member_id, choice=choice
            )
        except ValueError as exc:
            typer.echo(f"trading-council: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
        typer.echo(f"recorded vote on {proposal_id}: {member_id} -> {recorded.choice}")


@app.command(name="close-vote")
def close_vote_command(proposal_id: str = typer.Argument(...)) -> None:
    """Tally votes and set the proposal's final status."""
    settings = Settings()
    engine = db.init_db(settings.database_url)
    with db.get_session(engine) as session:
        try:
            result = close_vote(session, proposal_id=proposal_id, actor="cli")
        except ValueError as exc:
            typer.echo(f"trading-council: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
        typer.echo(
            f"closed vote on {proposal_id}: {result.status} "
            f"(yes={result.yes} no={result.no} abstain={result.abstain} "
            f"quorum_met={result.quorum_met})"
        )


@app.command()
def execute(proposal_id: str = typer.Argument(...)) -> None:
    """Stage (if needed) and submit a paper order for an approved proposal.

    Fails cleanly without broker credentials/state — it never silently no-ops.
    """
    settings = Settings()
    engine = db.init_db(settings.database_url)
    with db.get_session(engine) as session:
        try:
            existing = session.exec(
                select(Order).where(Order.proposal_id == proposal_id)
            ).first()
            if existing is None:
                stage_order_for_proposal(session, proposal_id, actor="cli", settings=settings)
            order = submit_order_for_proposal(
                session, proposal_id, actor="cli", settings=settings
            )
        except (ExecutionError, ValueError, BrokerCredentialsError) as exc:
            session.rollback()
            typer.echo(f"trading-council: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        session.commit()
        typer.echo(
            f"submitted order {order.id} for {proposal_id}: "
            f"{order.symbol} {order.side} {order.notional_cents}c status={order.status}"
        )


if __name__ == "__main__":  # pragma: no cover
    app()
