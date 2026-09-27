"""Tests for Coinbase Exchange API HMAC-SHA256 request signing."""
from __future__ import annotations

import base64
import hashlib
import hmac

from agent.coinbase.auth import build_auth_headers, sign_request


def test_sign_request_produces_valid_hmac() -> None:
    secret = base64.b64encode(b"my-test-secret").decode()
    ts = "1700000000.123"
    method = "GET"
    path = "/products/BTC-USD/ticker"

    sig = sign_request(secret, ts, method, path)

    # Verify independently
    message = f"{ts}{method}{path}"
    expected = base64.b64encode(
        hmac.new(b"my-test-secret", message.encode(), hashlib.sha256).digest()
    ).decode()

    assert sig == expected


def test_sign_request_includes_body() -> None:
    secret = base64.b64encode(b"secret").decode()
    ts = "1700000000"
    body = '{"type":"market","side":"buy"}'

    sig_with = sign_request(secret, ts, "POST", "/orders", body)
    sig_without = sign_request(secret, ts, "POST", "/orders")

    assert sig_with != sig_without


def test_sign_request_method_case_insensitive() -> None:
    secret = base64.b64encode(b"secret").decode()
    ts = "1700000000"
    path = "/accounts"

    assert sign_request(secret, ts, "get", path) == sign_request(secret, ts, "GET", path)


def test_build_auth_headers_keys() -> None:
    headers = build_auth_headers(
        api_key="my-api-key",
        secret_b64=base64.b64encode(b"secret").decode(),
        passphrase="my-pass",
        method="GET",
        path="/accounts",
    )
    assert set(headers.keys()) == {
        "CB-ACCESS-KEY",
        "CB-ACCESS-SIGN",
        "CB-ACCESS-TIMESTAMP",
        "CB-ACCESS-PASSPHRASE",
        "Content-Type",
    }
    assert headers["CB-ACCESS-KEY"] == "my-api-key"
    assert headers["CB-ACCESS-PASSPHRASE"] == "my-pass"
    assert headers["Content-Type"] == "application/json"
    # Signature must be non-empty base64
    sig = headers["CB-ACCESS-SIGN"]
    assert len(sig) > 0
    base64.b64decode(sig)  # must not raise
