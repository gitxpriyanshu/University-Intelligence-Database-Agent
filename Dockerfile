# ==============================================================================
# Build Stage: Installs dependencies and prepares the virtual environment
# ==============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml first to cache dependency installations
COPY pyproject.toml README.md /app/
COPY src/ /app/src/

# Install the package and its dependencies in a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# ==============================================================================
# Runner Stage: Lightweight final image with Playwright runtime dependencies
# ==============================================================================
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Playwright browser dependencies and Chromium binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/*

# Copy application source code and configurations
COPY pyproject.toml README.md /app/
COPY config/ /app/config/
COPY src/ /app/src/

# Ensure output directories exist and are writable
RUN mkdir -p /app/data/output /app/data/raw_cache

# Expose API server port
EXPOSE 8000

# Default entrypoint and command
ENTRYPOINT ["uia"]
CMD ["run"]
