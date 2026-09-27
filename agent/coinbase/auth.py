"""Coinbase Exchange API request signing (HMAC-SHA256)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def sign_request(
    secret_b64: str,
    timestamp: str,
    method: str,
    path: str,
    body: str = "",
) -> str:
    """Return base64-encoded HMAC-SHA256 signature for a Coinbase Exchange request.

    Args:
        secret_b64: Base64-encoded API secret.
        timestamp:  Unix epoch as a string (seconds, may include decimals).
        method:     HTTP method in any case — will be upper-cased.
        path:       Request path including query string, e.g. '/products/BTC-USD/ticker'.
        body:       Raw JSON request body; empty string for GET requests.
    """
    message = f"{timestamp}{method.upper()}{path}{body}"
    key = base64.b64decode(secret_b64)
    digest = hmac.new(key, message.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_auth_headers(
    api_key: str,
    secret_b64: str,
    passphrase: str,
    method: str,
    path: str,
    body: str = "",
) -> dict[str, str]:
    """Build the four required Coinbase Exchange authentication headers."""
    timestamp = str(time.time())
    return {
        "CB-ACCESS-KEY": api_key,
        "CB-ACCESS-SIGN": sign_request(secret_b64, timestamp, method, path, body),
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
