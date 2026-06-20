from decimal import Decimal

from trading_council.broker.base import (
    Broker,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    BrokerQuote,
    cents_to_dollars,
    mask_account_number,
    to_cents,
    to_cents_optional,
)


def test_to_cents_rounds_half_up():
    assert to_cents("100.00") == 10_000
    assert to_cents(Decimal("1.005")) == 101  # half-up, not banker's rounding
    assert to_cents(0) == 0


def test_to_cents_optional_passes_through_empty():
    assert to_cents_optional(None) is None
    assert to_cents_optional("") is None
    assert to_cents_optional("12.34") == 1234


def test_cents_to_dollars_roundtrips():
    assert cents_to_dollars(to_cents("42.50")) == Decimal("42.50")


def test_mask_account_number_keeps_only_last_four():
    assert mask_account_number("PA1234567890") == "****7890"
    assert mask_account_number("123") == "****"
    assert mask_account_number(None) == "unknown"


def test_value_objects_construct():
    BrokerAccount(
        account_id="x",
        account_number_masked="****7890",
        status="ACTIVE",
        currency="USD",
        cash_cents=1,
        equity_cents=2,
        buying_power_cents=3,
        trading_blocked=False,
        account_blocked=False,
        pattern_day_trader=False,
    )
    BrokerPosition(symbol="SPY", qty=Decimal("1"), side="long")
    BrokerQuote(symbol="SPY", bid_price=Decimal("1"), ask_price=Decimal("2"))
    BrokerOrder(
        broker_order_id="b",
        client_order_id="c",
        symbol="SPY",
        side="buy",
        status="accepted",
    )


def test_broker_protocol_is_runtime_checkable_and_has_no_raw_escape_hatch():
    methods = {m for m in dir(Broker) if not m.startswith("_")}
    assert methods == {
        "get_account",
        "get_positions",
        "get_latest_quote",
        "place_market_order",
        "get_order",
    }
