FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (default 8000, configurable via FASTMCP_PORT)
EXPOSE 8000

# Set default environment variables
ENV MCP_TRANSPORT=sse
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8000

# Run the MCP server
CMD ["python", "-m", "jellyseerr_mcp"]

