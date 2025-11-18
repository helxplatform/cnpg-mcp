# CloudNativePG MCP Server - Production Dockerfile
# Optimized for Kubernetes deployment with in-cluster authentication and OIDC support

FROM python:3.11-slim

# Metadata
LABEL maintainer="CloudNativePG MCP Server"
LABEL description="MCP Server for managing PostgreSQL clusters via CloudNativePG"
LABEL version="1.0.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/cnpg_mcp_server.py .
COPY src/auth_oidc.py .

# Create a non-root user for security
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

# Expose HTTP port
EXPOSE 4204

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:4204/healthz || exit 1

# Default to HTTP transport (for Kubernetes deployment)
# The server will use in-cluster config automatically when running in a pod
# OIDC configuration should be provided via environment variables:
#   OIDC_ISSUER, OIDC_AUDIENCE, OIDC_JWKS_URI (optional), DCR_PROXY_URL (optional)
CMD ["python", "cnpg_mcp_server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "4204"]
