# ============================================================
# Production Dockerfile — Day 12 × Day 09 Shopping Assistant
# Multi-stage, < 500 MB target, non-root user
# ============================================================

# Stage 1: Builder — compile native extensions (chromadb, grpc, etc.)
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Runtime — minimal image
FROM python:3.11-slim AS runtime

# Non-root user for security
RUN groupadd -r agent && useradd -r -g agent -d /app agent

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/agent/.local

# Copy Day 12 FastAPI layer
COPY app/ ./app/
COPY utils/ ./utils/

# Copy Day 09 source code and data
COPY src/ ./src/
COPY data/ ./data/

RUN chown -R agent:agent /app && \
    mkdir -p /app/src/.chroma && \
    chown -R agent:agent /app/src/.chroma

USER agent

ENV PATH=/home/agent/.local/bin:$PATH
# /app/src contains Day 09 modules (app/, provider/, rag/)
ENV PYTHONPATH=/app:/app/src:/home/agent/.local/lib/python3.11/site-packages
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ChromaDB persistence directory
ENV CHROMA_DIR=/app/src/.chroma

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
