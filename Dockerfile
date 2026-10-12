# syntax=docker/dockerfile:1

# Production image. Build: docker build -t dash .
# Run:   docker run --rm -p 127.0.0.1:8000:8000 dash

# Stage 1: build the virtual environment with uv.
FROM python:3.13.13-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

# Compile .pyc at build time. Copy (not hard-link) from the cache mount.
# Use the image's Python, never a downloaded one, so the runtime stage has the same Python.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, in their own layer, so a code change does not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Then the project. --no-editable installs it into site-packages,
# so the runtime stage needs only the virtual environment, not the source.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

ARG PLUGINS=""
COPY examples ./examples
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$PLUGINS" ]; then uv pip install --python /app/.venv/bin/python --no-deps $PLUGINS; fi


# Stage 2: runtime. No uv, no build tools, no source, not root.
FROM python:3.13.13-slim-trixie

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

# 0.0.0.0 inside the container. Publish the port on 127.0.0.1 only (see "Run" above).
CMD ["dash", "serve", "--host", "0.0.0.0", "--port", "8000"]
