"""Narrow broker interface and normalized value objects.

The app talks to brokers only through this surface so it is not Alpaca-coupled
everywhere. Money is normalized to integer cents; share quantities and prices stay
as ``Decimal`` because fractional shares and sub-cent prices are real. There is no
generic "raw API call" method by design — every capability is an explicit method.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol, runtime_checkable

Side = Literal["buy", "sell"]


class BrokerCredentialsError(RuntimeError):
    """Raised when required broker credentials are missing.

    The message never includes secret values — only which credential set is absent.
    """


def to_cents(value: Decimal | int | float | str) -> int:
    """Convert a dollar amount to integer cents, rounding half-up."""
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_cents_optional(value: Decimal | int | float | str | None) -> int | None:
    """Like :func:`to_cents` but passes ``None``/empty through unchanged."""
    if value is None or value == "":
        return None
    return to_cents(value)


def cents_to_dollars(cents: int) -> Decimal:
    """Convert integer cents back to a ``Decimal`` dollar amount."""
    return Decimal(cents) / 100


def mask_account_number(number: str | None) -> str:
    """Mask a broker account number to its last 4 digits; never echo the full value."""
    if not number:
        return "unknown"
    text = str(number)
    return f"****{text[-4:]}" if len(text) > 4 else "****"


@dataclass(frozen=True)
class BrokerAccount:
    account_id: str
    account_number_masked: str
    status: str
    currency: str
    cash_cents: int
    equity_cents: int
    buying_power_cents: int
    trading_blocked: bool
    account_blocked: bool
    pattern_day_trader: bool


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: Decimal
    side: str
    avg_entry_price_cents: int | None = None
    market_value_cents: int | None = None


@dataclass(frozen=True)
class BrokerQuote:
    symbol: str
    bid_price: Decimal | None
    ask_price: Decimal | None


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    notional_cents: int | None = None
    qty: Decimal | None = None
    filled_qty: Decimal | None = None
    filled_avg_price_cents: int | None = None


@runtime_checkable
class Broker(Protocol):
    """Typed broker surface. Implementations must not expose raw API escape hatches."""

    def get_account(self) -> BrokerAccount: ...

    def get_positions(self) -> list[BrokerPosition]: ...

    def get_latest_quote(self, symbol: str) -> BrokerQuote: ...

    def place_market_order(
        self,
        *,
        symbol: str,
        side: Side,
        notional_cents: int,
        client_order_id: str,
    ) -> BrokerOrder: ...

    def get_order(self, broker_order_id: str) -> BrokerOrder: ...
