# Trading Council Agent

Discord-operated friend trading-council agent. **Paper trading first.**

A self-hosted Python service for a friend group to propose, vote on, reconcile, report on,
and execute paper trades through Alpaca. Order execution is deterministic and gated; any
LLM/Discord layer should sit outside the safety-critical services and call this app through
explicit CLI/API boundaries. Live trading stays blocked until an explicit, audited readiness
gate passes in a later phase.

This is a standalone app repo. It intentionally does not depend on, configure, or share
runtime state with Steve/Hermes.

## Status

Implemented so far:

- Project scaffold with `uv`, `pytest`, `ruff`, settings, and CLI health check.
- SQLite ledger models for members, proposals, votes, orders, positions, snapshots, and audit logs.
- Fail-closed rules/risk/voting foundation using `config/rules.yaml`.
- Narrow Alpaca broker adapter with mocked tests and read-only account check.
- Proposal, voting, paper execution staging/submission services.
- Reconciliation and reporting services:
  - `reconcile`
  - `portfolio`
  - `weekly-recap`

Still intentionally not included:

- Discord bot/application layer.
- Cron/Hermes automation.
- Deployment/systemd runbook.
- Live trading enablement.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Alpaca paper account credentials for broker-backed commands.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in values locally; never commit .env
```

Minimum useful local `.env` values for Alpaca paper mode:

```bash
TRADING_COUNCIL_MODE=paper
ALPACA_PAPER_API_KEY=...
ALPACA_PAPER_SECRET_KEY=...
```

Do not commit `.env` or real credentials.

## Common commands

Health check:

```bash
uv run trading-council status
```

Initialize the local SQLite DB:

```bash
uv run trading-council init-db
```

Read-only Alpaca account check:

```bash
uv run trading-council alpaca-account
```

Create a proposal:

```bash
uv run trading-council propose \
  --symbol QQQ \
  --side buy \
  --allocation-pct 20 \
  --thesis "Momentum exposure" \
  --risk "Could draw down if tech sells off" \
  --exit-condition "Review weekly or exit on risk trigger" \
  --created-by noah
```

Record and close votes:

```bash
uv run trading-council vote 2026-W26-A --member-id DISCORD_ID --choice yes
uv run trading-council close-vote 2026-W26-A
```

Execute an approved proposal in paper mode:

```bash
uv run trading-council execute 2026-W26-A
```

Reconcile account/positions from Alpaca paper into the local ledger:

```bash
uv run trading-council reconcile
```

Print reports:

```bash
uv run trading-council portfolio
uv run trading-council weekly-recap
```

Use a temp DB for safe smoke tests:

```bash
TRADING_COUNCIL_DATABASE_URL=sqlite:////tmp/trading_council_smoke.db \
  uv run trading-council init-db

TRADING_COUNCIL_DATABASE_URL=sqlite:////tmp/trading_council_smoke.db \
  uv run trading-council portfolio
```

## Safety defaults

- **Paper mode is the default.** `TRADING_COUNCIL_MODE` defaults to `paper`.
- **Live mode is blocked** unless both `TRADING_COUNCIL_MODE=live` and
  `TRADING_COUNCIL_LIVE_ENABLED=true` are set; paper trading remains the intended v1 path.
- **No live execution automation exists yet.** Current execution paths are paper-only.
- **Rules fail closed.** Unknown rule-config keys, invalid symbols, invalid sides, and unsafe
  allocations are rejected.
- **Broker access is narrow.** The app uses explicit broker methods rather than exposing raw
  Alpaca clients to callers.
- **Secrets stay local.** Alpaca/Discord credentials belong in `.env`, which is git-ignored.
- **Audit logs are first-class.** Proposal creation, voting, staging, submission, and
  reconciliation write audit events.

## Development

```bash
uv run pytest        # run tests
uv run ruff check .  # lint
```

For PR review, also smoke the CLI against a fresh temp DB:

```bash
rm -f /tmp/trading_council_review.db
TRADING_COUNCIL_DATABASE_URL=sqlite:////tmp/trading_council_review.db \
  uv run trading-council init-db
TRADING_COUNCIL_DATABASE_URL=sqlite:////tmp/trading_council_review.db \
  uv run trading-council portfolio
TRADING_COUNCIL_DATABASE_URL=sqlite:////tmp/trading_council_review.db \
  uv run trading-council weekly-recap
```
