# uv publishes 0.12.x only on Debian trixie, so builder and runtime both use trixie
# (same glibc, so the copied venv's compiled wheels work in the runtime image).

# --- builder: resolve and install locked runtime dependencies into /app/.venv ---
FROM ghcr.io/astral-sh/uv:0.12.16-python3.12-trixie-slim AS builder
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# --- runtime: slim image with the venv and the code, no uv, non-root ---
FROM python:3.12.15-slim-trixie AS runtime
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=builder /app/.venv /app/.venv
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY --chmod=755 docker/entrypoint.sh ./docker/
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# --- test: builder plus the dev group and the tests ---
FROM builder AS test
WORKDIR /app
RUN uv sync --locked --no-install-project
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini pyproject.toml ./
COPY tests/ ./tests/
ENV PATH=/app/.venv/bin:$PATH
CMD ["pytest", "-q"]
