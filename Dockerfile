FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependencies first for layer caching; project code copied below.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

COPY src/ src/
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Topology A: keep-alive container; MCP attaches via `docker exec -i`.
CMD ["tail", "-f", "/dev/null"]
