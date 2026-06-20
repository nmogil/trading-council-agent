# Trading Council Agent

Discord-operated friend trading-council agent. **Paper trading first.**

A self-hosted Python service for a friend group to propose, vote on, and (eventually)
execute trades through Alpaca. Order execution is deterministic and gated; the LLM layer
only drafts briefings and proposals. Live trading stays blocked until an explicit,
audited readiness gate passes.

This is a standalone app repo. It intentionally does not depend on, configure, or share
runtime state with Steve/Hermes; later integrations should call this app through explicit
CLI/API boundaries.

## Status

Phase 1 — repo bootstrap and quality gates. The runnable surface today is a minimal CLI
plus a settings loader that defaults to paper mode.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
cp .env.example .env   # then fill in values locally; never commit .env
```

## Usage

```bash
uv run trading-council status   # prints: trading-council: ok
```

## Safety defaults

- **Paper mode is the default.** `TRADING_COUNCIL_MODE` defaults to `paper`.
- **Live mode is blocked** unless both `TRADING_COUNCIL_MODE=live` and
  `TRADING_COUNCIL_LIVE_ENABLED=true` are set; otherwise settings fail to load.
- Secrets (Alpaca / Discord tokens) live only in `.env`, which is git-ignored.
  See `.env.example` for the full variable list.

## Development

```bash
uv run pytest        # run tests
uv run ruff check .  # lint
```
