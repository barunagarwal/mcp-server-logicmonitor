# Description: Container image for LogicMonitor MCP server.
# Description: Supports both stdio and HTTP transport modes.

# python:3.11.17-slim-bookworm, digest read from Docker Hub 2026-10-21
FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf AS builder

WORKDIR /app

# Install uv (ghcr.io/astral-sh/uv:0.9.27, the version CI pins)
COPY --from=ghcr.io/astral-sh/uv:0.9.27@sha256:143b40f4ab56a780f43377604702107b5a35f83a4453daf1e4be691358718a6a /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

# Export the locked runtime dependencies with hashes, and build the wheel.
# uv exports the project itself as "-e ." with no hash, which --require-hashes
# refuses, so the project is left out of the export and its wheel is installed
# on its own in the runtime stage.
RUN uv export --no-dev --extra http --frozen --no-emit-project --format requirements-txt -o /app/requirements.txt \
    && uv build --wheel

# python:3.11.17-slim-bookworm, digest read from Docker Hub 2026-10-21
FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

WORKDIR /app

# Copy the locked requirements and the built wheel from builder
COPY --from=builder /app/requirements.txt /app/dist/*.whl /app/

# Install exactly what uv.lock pins, checked by hash, then the wheel without
# resolving anything further
RUN pip install --no-cache-dir --no-deps --require-hashes -r /app/requirements.txt \
    && pip install --no-cache-dir --no-deps /app/*.whl \
    && rm /app/requirements.txt /app/*.whl

# Create non-root user with a fixed UID, which deploy/k8s/deployment.yaml
# sets as runAsUser
RUN useradd --uid 10001 --create-home --shell /bin/bash mcp
USER 10001

# HTTP mode defaults
ENV LM_TRANSPORT=http
ENV LM_HTTP_HOST=0.0.0.0
ENV LM_HTTP_PORT=8080
EXPOSE 8080

# Health check on the image's own Python; urlopen raises on a non-2xx answer
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('LM_HTTP_PORT', '8080'), timeout=5).status == 200 else 1)"]

# Entry point
ENTRYPOINT ["lm-mcp-server"]
