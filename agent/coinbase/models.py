"""Pydantic models for Coinbase Exchange API responses."""
from __future__ import annotations

from pydantic import BaseModel


class Ticker(BaseModel):
    """Response from GET /products/{id}/ticker."""

    price: str
    bid: str = ""
    ask: str = ""
    volume: str = ""
    time: str = ""
    trade_id: int = 0
    size: str = ""

    @property
    def price_float(self) -> float:
        return float(self.price)


class Account(BaseModel):
    """One entry from GET /accounts."""

    id: str
    currency: str
    balance: str
    available: str
    hold: str
    profile_id: str = ""
    trading_enabled: bool = True

    @property
    def available_float(self) -> float:
        return float(self.available)


class Order(BaseModel):
    """Response from POST /orders."""

    id: str
    product_id: str
    side: str
    type: str
    status: str
    funds: str = ""
    specified_funds: str = ""
    filled_size: str = ""
    executed_value: str = ""
    fill_fees: str = ""
    created_at: str = ""
    settled: bool = False
