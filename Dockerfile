FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Set default port (can be overridden)
ARG SHIM_PORT=4001
ENV SHIM_PORT=${SHIM_PORT}

# Expose the port
EXPOSE ${SHIM_PORT}

# Run the server
CMD uvicorn src.server:app --host 0.0.0.0 --port ${SHIM_PORT}
