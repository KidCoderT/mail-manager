# MailBrief as an always-on service: the container's only job is `mailbrief serve`.
# Secrets (.env) and mail (data/) are never copied in: .env comes from compose's env_file, data/ is a volume.
FROM python:3.11-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv

WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Dependencies first (cached until uv.lock changes), then the code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY mailbrief ./mailbrief
RUN uv sync --frozen --no-dev \
 && uv run --no-sync playwright install --with-deps chromium --no-shell \
 && rm -rf /var/lib/apt/lists/*

# Not root: uid 1000 is usually your user on a Linux server, so the mounted data/ stays writable for both.
RUN useradd --uid 1000 --create-home app && mkdir -p /app/data && chown -R app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["mailbrief", "serve"]
