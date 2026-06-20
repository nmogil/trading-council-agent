"""Unit tests for the Alpaca adapter. All Alpaca calls are mocked — no network."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from trading_council.broker.alpaca import AlpacaBroker
from trading_council.broker.base import BrokerCredentialsError
from trading_council.settings import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        TRADING_COUNCIL_MODE="paper",
        ALPACA_PAPER_API_KEY="paper-key",
        ALPACA_PAPER_SECRET_KEY="paper-secret",
    )
    base.update(overrides)
    return Settings(**base)


class FakeTradingClient:
    def __init__(self):
        self.submitted = None

    def get_account(self):
        return SimpleNamespace(
            id="acct-1",
            account_number="PA987654321",
            status="ACTIVE",
            currency="USD",
            cash="1000.50",
            equity="2000.00",
            buying_power="3000.00",
            trading_blocked=False,
            account_blocked=False,
            pattern_day_trader=False,
        )

    def get_all_positions(self):
        # Mix object + dict to exercise defensive extraction.
        return [
            SimpleNamespace(
                symbol="spy",
                qty="3",
                side="long",
                avg_entry_price="400.00",
                market_value="1200.00",
            ),
            {"symbol": "QQQ", "qty": "1", "side": "long",
             "avg_entry_price": None, "market_value": "350.00"},
        ]

    def submit_order(self, order_data):
        self.submitted = order_data
        return SimpleNamespace(
            id="broker-1",
            client_order_id=order_data.client_order_id,
            symbol=order_data.symbol,
            side="buy",
            status="accepted",
            notional=str(order_data.notional),
            qty=None,
            filled_qty="0",
            filled_avg_price=None,
        )

    def get_order_by_id(self, order_id):
        return SimpleNamespace(
            id=order_id,
            client_order_id="cid-1",
            symbol="SPY",
            side="buy",
            status="filled",
            notional="50.00",
            qty=None,
            filled_qty="0.125",
            filled_avg_price="400.00",
        )


class FakeDataClient:
    def get_stock_latest_quote(self, request_params):
        symbol = request_params.symbol_or_symbols
        return {symbol: SimpleNamespace(bid_price="399.90", ask_price="400.10")}


def _broker(**overrides):
    return AlpacaBroker(
        _settings(**overrides),
        trading_client=FakeTradingClient(),
        data_client=FakeDataClient(),
    )


def test_get_account_normalizes_and_masks():
    account = _broker().get_account()
    assert account.account_number_masked == "****4321"
    assert account.cash_cents == 100_050
    assert account.equity_cents == 200_000
    assert account.buying_power_cents == 300_000
    assert account.status == "ACTIVE"
    assert account.trading_blocked is False


def test_get_positions_normalizes_objects_and_dicts():
    positions = _broker().get_positions()
    assert {p.symbol for p in positions} == {"SPY", "QQQ"}
    spy = next(p for p in positions if p.symbol == "SPY")
    assert spy.qty == Decimal("3")
    assert spy.avg_entry_price_cents == 40_000
    qqq = next(p for p in positions if p.symbol == "QQQ")
    assert qqq.avg_entry_price_cents is None  # missing field stays None


def test_get_latest_quote_normalizes_symbol():
    quote = _broker().get_latest_quote("spy")
    assert quote.symbol == "SPY"
    assert quote.bid_price == Decimal("399.90")
    assert quote.ask_price == Decimal("400.10")


def test_place_market_order_sets_client_order_id_and_notional():
    trading_client = FakeTradingClient()
    broker = AlpacaBroker(_settings(), trading_client=trading_client, data_client=FakeDataClient())
    order = broker.place_market_order(
        symbol="spy", side="BUY", notional_cents=5000, client_order_id="cid-xyz"
    )
    submitted = trading_client.submitted
    assert submitted.client_order_id == "cid-xyz"  # idempotency key set
    assert submitted.symbol == "SPY"
    assert submitted.notional == Decimal("50.00")
    assert str(submitted.side).lower().endswith("buy")
    assert order.broker_order_id == "broker-1"
    assert order.notional_cents == 5000


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(symbol="SPY", side="hold", notional_cents=5000, client_order_id="c"),
        dict(symbol="SPY", side="buy", notional_cents=0, client_order_id="c"),
        dict(symbol="SPY", side="buy", notional_cents=5000, client_order_id=""),
    ],
)
def test_place_market_order_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        _broker().place_market_order(**kwargs)


def test_get_order_normalizes_fractional_fill():
    order = _broker().get_order("broker-1")
    assert order.status == "filled"
    assert order.filled_qty == Decimal("0.125")
    assert order.filled_avg_price_cents == 40_000


def test_paper_mode_selects_paper_credentials():
    broker = AlpacaBroker(_settings(TRADING_COUNCIL_MODE="paper"))
    api_key, secret_key, paper = broker._credentials()
    assert (api_key, secret_key, paper) == ("paper-key", "paper-secret", True)


def test_live_mode_selects_live_credentials():
    broker = AlpacaBroker(
        _settings(
            TRADING_COUNCIL_MODE="live",
            TRADING_COUNCIL_LIVE_ENABLED="true",
            ALPACA_LIVE_API_KEY="live-key",
            ALPACA_LIVE_SECRET_KEY="live-secret",
        )
    )
    api_key, secret_key, paper = broker._credentials()
    assert (api_key, secret_key, paper) == ("live-key", "live-secret", False)


def test_missing_credentials_raises_without_echoing_secrets():
    broker = AlpacaBroker(_settings(ALPACA_PAPER_API_KEY="", ALPACA_PAPER_SECRET_KEY=""))
    with pytest.raises(BrokerCredentialsError) as exc:
        broker._credentials()
    assert "paper" in str(exc.value)



def test_raw_clients_are_not_public_escape_hatches():
    broker = _broker()
    assert not hasattr(broker, "trading_client")
    assert not hasattr(broker, "data_client")
