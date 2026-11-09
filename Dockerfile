# One image for every Python process: core (api, media, worker), simulator and migrations.
# The command picks the process (ADR 0025):
#   docker run IMAGE core      # python -m pramana_core
#   docker run IMAGE sim       # python -m pramana_sim
#   docker run IMAGE migrate   # alembic upgrade head
# Local development stays Docker-free (ADR 0005); this image is for deployment only.

FROM python:3.11-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so source edits do not invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY packages/domain/pyproject.toml packages/domain/
COPY packages/engine/pyproject.toml packages/engine/
COPY services/sim/pyproject.toml services/sim/
COPY services/core/pyproject.toml services/core/
COPY eval/pyproject.toml eval/
RUN uv sync --frozen --no-dev --no-install-workspace
COPY packages packages
COPY services services
COPY eval eval
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm AS runtime
RUN useradd --system --uid 10001 --home /app pramana
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY packs /app/packs
COPY services/core/alembic.ini /app/services/core/alembic.ini
COPY services/core/alembic /app/services/core/alembic
COPY docker/entrypoint.sh /usr/local/bin/pramana-entrypoint
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PRAMANA_PACKS_DIR=/app/packs \
    TTS_CACHE_DIR=/tmp/pramana/tts \
    LLM_CACHE_DIR=/tmp/pramana/llm \
    CORE_HOST=0.0.0.0 \
    SIM_HOST=0.0.0.0
USER pramana
EXPOSE 8080
ENTRYPOINT ["pramana-entrypoint"]
CMD ["core"]
