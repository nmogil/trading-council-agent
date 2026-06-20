"""Broker abstraction package: a narrow, typed interface plus the Alpaca adapter."""

from trading_council.broker.base import (
    Broker,
    BrokerAccount,
    BrokerCredentialsError,
    BrokerOrder,
    BrokerPosition,
    BrokerQuote,
)

__all__ = [
    "Broker",
    "BrokerAccount",
    "BrokerCredentialsError",
    "BrokerOrder",
    "BrokerPosition",
    "BrokerQuote",
]
