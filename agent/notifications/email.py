"""Email notifications via SMTP.

All functions are fire-and-forget: they log failures but never raise,
so a broken SMTP config cannot crash the agent.
"""
from __future__ import annotations

import smtplib
import traceback
from email.mime.text import MIMEText

import structlog

from agent.core.config import Settings

logger = structlog.get_logger()


def _send(settings: Settings, subject: str, body: str) -> None:
    """Send a plain-text email.  No-op if SMTP is not configured."""
    if not all([settings.smtp_host, settings.smtp_user, settings.notify_email]):
        return
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.notify_email

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())

        logger.info("email_sent", subject=subject, to=settings.notify_email)
    except Exception:
        logger.error("email_failed", subject=subject, detail=traceback.format_exc())


def notify_buy_executed(
    settings: Settings,
    *,
    coin: str,
    amount_usd: float,
    order_id: str,
    status: str,
) -> None:
    subject = f"[crypto-agent] Buy executed: ${amount_usd:.2f} of {coin}"
    body = (
        f"A buy order was successfully placed.\n\n"
        f"  Coin:      {coin}\n"
        f"  Amount:    ${amount_usd:.2f} USD\n"
        f"  Order ID:  {order_id}\n"
        f"  Status:    {status}\n"
    )
    _send(settings, subject, body)


def notify_guardrail_tripped(
    settings: Settings,
    *,
    coin: str,
    amount_usd: float,
    reason: str,
) -> None:
    subject = f"[crypto-agent] Buy blocked: {coin}"
    body = (
        f"A buy was blocked by a guardrail.\n\n"
        f"  Coin:    {coin}\n"
        f"  Amount:  ${amount_usd:.2f} USD\n"
        f"  Reason:  {reason}\n"
    )
    _send(settings, subject, body)


def notify_agent_error(settings: Settings, *, coin: str, error: str) -> None:
    subject = f"[crypto-agent] Error monitoring {coin}"
    body = f"The buying agent encountered an error:\n\n{error}\n"
    _send(settings, subject, body)
