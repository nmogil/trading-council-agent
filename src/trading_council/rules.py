"""Trading constitution: typed, validated rules loaded from ``config/rules.yaml``.

Validation fails closed — any malformed config raises rather than silently
defaulting. Loader supports an explicit path override so tests can point at
fixtures instead of the repo's real config.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# rules.py lives at src/trading_council/rules.py; repo root is two parents up.
DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "rules.yaml"


class ModeDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_first: bool = True


class Universe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_symbols: list[str]

    @field_validator("allowed_symbols")
    @classmethod
    def _non_empty_uppercase(cls, symbols: list[str]) -> list[str]:
        if not symbols:
            raise ValueError("allowed_symbols must not be empty")
        cleaned = [s.strip().upper() for s in symbols]
        if any(not s for s in cleaned):
            raise ValueError("allowed_symbols must not contain empty symbols")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("allowed_symbols must not contain duplicates")
        return cleaned


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_position_allocation_pct: int = Field(ge=0, le=100)
    max_new_trades_per_week: int = Field(ge=0)
    max_order_notional_cents: int = Field(ge=0)
    quorum_pct: int = Field(ge=0, le=100)
    require_majority_pct: int = Field(ge=0, le=100)
    allow_margin: bool = False
    allow_shorting: bool = False
    allow_options: bool = False
    allow_crypto: bool = False


class Execution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_approval_for_live: bool = True
    require_approval_for_paper: bool = False


class TradingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    mode_defaults: ModeDefaults = Field(default_factory=ModeDefaults)
    universe: Universe
    risk: Risk
    execution: Execution

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.strip().upper()

    def is_allowed_symbol(self, symbol: str) -> bool:
        return self.normalize_symbol(symbol) in self.universe.allowed_symbols


def load_rules(path: str | Path | None = None) -> TradingRules:
    """Load and validate the trading rules from YAML."""
    rules_path = Path(path) if path is not None else DEFAULT_RULES_PATH
    data = yaml.safe_load(rules_path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"rules file {rules_path} must contain a mapping")
    return TradingRules.model_validate(data)
