FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

COPY --from=ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7 /uv /uvx /bin/

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ffmpeg=7:5.1.9-0+deb12u1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system eva \
    && useradd --system --gid eva --home-dir /app --shell /usr/sbin/nologin eva \
    && mkdir -p /app/state /tmp/eva-terminal \
    && chown -R eva:eva /app /tmp/eva-terminal

# Install dependencies first (cached layer). Runtime images exclude dev tools.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install Playwright system dependencies and Chromium browser in a shared,
# read-only location available to the non-root runtime user.
RUN uv run playwright install-deps chromium \
    && mkdir -p /ms-playwright \
    && uv run playwright install chromium \
    && chmod -R a+rX /ms-playwright

COPY src/ src/

# Install the project itself without development dependencies.
RUN uv sync --frozen --no-dev \
    && chown -R eva:eva /app

USER eva

ENV TERMINAL_WORKDIR=/tmp/eva-terminal \
    TERMINAL_COMMAND_MODE=allowlist \
    TERMINAL_NETWORK_ENABLED=false \
    NOPECHA_ENABLED=false \
    INTERACTION_LOG_ENABLED=false \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

CMD ["/app/.venv/bin/eva"]
