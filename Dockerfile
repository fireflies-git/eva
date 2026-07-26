FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Install Playwright system deps and Chromium browser
RUN uv run playwright install-deps chromium
RUN uv run playwright install chromium

# Copy source code
COPY src/ src/

# Install the project itself
RUN uv sync --frozen

CMD ["uv", "run", "eva"]
