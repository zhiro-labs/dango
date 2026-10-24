FROM python:3.12-slim

# Same uv version as CI (.github/workflows/test.yml) and the one that wrote
# uv.lock, so `uv sync --frozen` reads the lockfile the same way everywhere.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

WORKDIR /app

# Cache dependencies separately from source changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Store example configs at a path not shadowed by the config volume mount
RUN mkdir -p /app/config.examples && \
    cp /app/config/runtime.yml.example /app/config.examples/ && \
    cp /app/config/chat_sys_prompt.txt.example /app/config.examples/

# Same for custom-extension templates — the ./custom volume mount shadows /app/custom,
# so keep a copy the entrypoint can seed into the (empty) mounted dir on first run.
RUN mkdir -p /app/custom.examples && \
    cp /app/custom/*.example /app/custom/README.md /app/custom.examples/

# Same for skill templates — the ./skills volume mount shadows /app/skills,
# so keep a copy (README + example/) the entrypoint can seed on first run.
RUN mkdir -p /app/skills.examples && \
    cp -r /app/skills/. /app/skills.examples/

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
