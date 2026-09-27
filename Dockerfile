# syntax=docker/dockerfile:1

# ── builder ───────────────────────────────────────────────────────────────────
FROM python:3.11.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --compile-bytecode

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:3.11.13-slim-bookworm AS runtime

WORKDIR /app

RUN addgroup --gid 1001 appgroup && \
    adduser --disabled-password --gecos "" --uid 1001 --gid 1001 appuser

COPY --from=builder --chown=appuser:appgroup /app/.venv ./.venv
COPY --chown=appuser:appgroup agent/ ./agent/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.base.name="python:3.11.13-slim-bookworm" \
      org.opencontainers.image.source="https://github.com/your-org/crypto-buying-agent"

USER appuser

CMD ["crypto-agent", "monitor"]
