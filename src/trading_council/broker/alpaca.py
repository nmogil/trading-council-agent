"""Alpaca adapter implementing the :class:`~trading_council.broker.base.Broker` surface.

Paper vs live credentials are chosen from ``Settings.mode`` (default paper). Clients
are built lazily so unit tests can inject mocks and never touch the network. Raw
Alpaca objects are converted to the package's normalized value objects; secrets and
full account numbers are never logged or returned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from trading_council.broker.base import (
    BrokerAccount,
    BrokerCredentialsError,
    BrokerOrder,
    BrokerPosition,
    BrokerQuote,
    Side,
    cents_to_dollars,
    mask_account_number,
    to_cents,
    to_cents_optional,
)
from trading_council.settings import Settings


def _get(obj: Any, name: str) -> Any:
    """Read an attribute from an Alpaca model object or a raw dict, defensively."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _to_str(value: Any) -> str:
    """Stringify an enum/object value (Alpaca enums stringify to ``Enum.NAME``)."""
    return getattr(value, "value", value) if value is not None else ""


def _decimal_optional(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


class AlpacaBroker:
    """Broker adapter backed by ``alpaca-py``.

    Pass ``trading_client`` / ``data_client`` to inject mocks in tests. In production
    they are constructed on first use from the credentials selected by ``settings.mode``.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        trading_client: Any | None = None,
        data_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.mode = settings.mode.strip().lower()
        self._trading_client = trading_client
        self._data_client = data_client

    # -- client construction -------------------------------------------------

    def _credentials(self) -> tuple[str, str, bool]:
        """Return ``(api_key, secret_key, paper)`` for the active mode.

        Raises :class:`BrokerCredentialsError` (no secret values in the message) if a
        required credential is missing.
        """
        if self.mode == "live":
            api_key = self.settings.alpaca_live_api_key
            secret_key = self.settings.alpaca_live_secret_key
            paper = False
        else:
            api_key = self.settings.alpaca_paper_api_key
            secret_key = self.settings.alpaca_paper_secret_key
            paper = True
        if not api_key or not secret_key:
            raise BrokerCredentialsError(
                f"missing Alpaca {self.mode} credentials; set the relevant "
                "ALPACA_*_API_KEY and ALPACA_*_SECRET_KEY environment variables"
            )
        return api_key, secret_key, paper

    def _get_trading_client(self) -> Any:
        if self._trading_client is None:
            from alpaca.trading.client import TradingClient

            api_key, secret_key, paper = self._credentials()
            self._trading_client = TradingClient(api_key, secret_key, paper=paper)
        return self._trading_client

    def _get_data_client(self) -> Any:
        if self._data_client is None:
            from alpaca.data.historical import StockHistoricalDataClient

            api_key, secret_key, _paper = self._credentials()
            self._data_client = StockHistoricalDataClient(api_key, secret_key)
        return self._data_client

    # -- read operations -----------------------------------------------------

    def get_account(self) -> BrokerAccount:
        raw = self._get_trading_client().get_account()
        return BrokerAccount(
            account_id=str(_get(raw, "id") or ""),
            account_number_masked=mask_account_number(_get(raw, "account_number")),
            status=_to_str(_get(raw, "status")),
            currency=str(_get(raw, "currency") or ""),
            cash_cents=to_cents(_get(raw, "cash") or 0),
            equity_cents=to_cents(_get(raw, "equity") or 0),
            buying_power_cents=to_cents(_get(raw, "buying_power") or 0),
            trading_blocked=bool(_get(raw, "trading_blocked")),
            account_blocked=bool(_get(raw, "account_blocked")),
            pattern_day_trader=bool(_get(raw, "pattern_day_trader")),
        )

    def get_positions(self) -> list[BrokerPosition]:
        raw_positions = self._get_trading_client().get_all_positions()
        return [
            BrokerPosition(
                symbol=str(_get(p, "symbol") or "").upper(),
                qty=Decimal(str(_get(p, "qty") or "0")),
                side=_to_str(_get(p, "side")),
                avg_entry_price_cents=to_cents_optional(_get(p, "avg_entry_price")),
                market_value_cents=to_cents_optional(_get(p, "market_value")),
            )
            for p in raw_positions
        ]

    def get_latest_quote(self, symbol: str) -> BrokerQuote:
        from alpaca.data.requests import StockLatestQuoteRequest

        symbol_n = symbol.strip().upper()
        response = self._get_data_client().get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol_n)
        )
        # The API returns a dict keyed by symbol; tolerate a bare quote too.
        quote = response.get(symbol_n) if isinstance(response, dict) else response
        return BrokerQuote(
            symbol=symbol_n,
            bid_price=_decimal_optional(_get(quote, "bid_price")),
            ask_price=_decimal_optional(_get(quote, "ask_price")),
        )

    def get_order(self, broker_order_id: str) -> BrokerOrder:
        raw = self._get_trading_client().get_order_by_id(broker_order_id)
        return _order_from_raw(raw)

    # -- write operations ----------------------------------------------------

    def place_market_order(
        self,
        *,
        symbol: str,
        side: Side,
        notional_cents: int,
        client_order_id: str,
    ) -> BrokerOrder:
        """Submit a notional market order. ``client_order_id`` enforces idempotency."""
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        symbol_n = symbol.strip().upper()
        side_n = side.strip().lower()
        if side_n not in {"buy", "sell"}:
            raise ValueError(f"invalid side {side!r}")
        if notional_cents <= 0:
            raise ValueError("notional_cents must be greater than 0")
        if not client_order_id:
            raise ValueError("client_order_id is required for idempotency")

        order_request = MarketOrderRequest(
            symbol=symbol_n,
            notional=cents_to_dollars(notional_cents),
            side=OrderSide.BUY if side_n == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        raw = self._get_trading_client().submit_order(order_request)
        return _order_from_raw(raw)


def _order_from_raw(raw: Any) -> BrokerOrder:
    """Convert an Alpaca order object/dict into a normalized :class:`BrokerOrder`."""
    return BrokerOrder(
        broker_order_id=str(_get(raw, "id") or ""),
        client_order_id=str(_get(raw, "client_order_id") or ""),
        symbol=str(_get(raw, "symbol") or "").upper(),
        side=_to_str(_get(raw, "side")),
        status=_to_str(_get(raw, "status")),
        notional_cents=to_cents_optional(_get(raw, "notional")),
        qty=_decimal_optional(_get(raw, "qty")),
        filled_qty=_decimal_optional(_get(raw, "filled_qty")),
        filled_avg_price_cents=to_cents_optional(_get(raw, "filled_avg_price")),
    )
