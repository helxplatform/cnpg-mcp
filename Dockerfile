FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server code
COPY cnpg_mcp_server.py .

# Create a non-root user
RUN useradd -m -u 1000 mcpuser && \
    chown -R mcpuser:mcpuser /app

USER mcpuser

# Set environment variables
ENV PYTHONUNBUFFERED=1

# The server runs as a long-running process waiting for stdio
CMD ["python", "cnpg_mcp_server.py"]
