#!/bin/bash

set -e

# Load .env file if it exists
if [ -f .env ]; then
  echo "Loading environment variables from .env file..."
  export $(grep -v '^#' .env | xargs)
fi

# Export default environment variables if not set
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
export OLLAMA_MODEL=${OLLAMA_MODEL:-minimax-m2:cloud}
export SHIM_PORT=${SHIM_PORT:-4001}
export LOG_LEVEL=${LOG_LEVEL:-info}

echo "Starting Ollama-Anthropic shim..."
echo "OLLAMA_BASE_URL: $OLLAMA_BASE_URL"
echo "OLLAMA_MODEL: $OLLAMA_MODEL"
echo "SHIM_PORT: $SHIM_PORT"
echo "LOG_LEVEL: $LOG_LEVEL"
echo ""

# Start the service
docker compose up -d --build

echo ""
echo "✓ Shim is running at http://localhost:$SHIM_PORT"
echo ""
echo "Test the health endpoint:"
echo "  curl http://localhost:$SHIM_PORT/health"
echo ""
echo "View logs:"
echo "  docker compose logs -f shim"
echo ""
echo "Stop the service:"
echo "  ./down.sh"
