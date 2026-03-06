FROM python:3.11-slim

# IfcOpenShell needs these system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files first for better layer caching
COPY pyproject.toml ./
COPY src/ ./src/
COPY data/ ./data/

# Install the package and its dependencies
RUN pip install --no-cache-dir -e .

# Prevent Python stdout buffering — critical for MCP stdio transport
ENV PYTHONUNBUFFERED=1

# MCP servers communicate over stdio by default.
# To expose over HTTP/SSE for testing, set MCP_TRANSPORT=sse and bind a port.
ENV MCP_TRANSPORT=stdio

# Ensure /tmp is writable for base64 temp file decoding
# (needed if container runs with --read-only)
VOLUME /tmp

CMD ["python", "-m", "lvi_mcp.server"]
