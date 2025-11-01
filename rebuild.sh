#!/bin/bash

set -e

echo "Rebuilding Ollama-Anthropic shim..."

docker compose down
docker compose build --no-cache
docker compose up -d

echo ""
echo "✓ Shim rebuilt and running at http://localhost:${SHIM_PORT:-4001}"
echo ""
echo "View logs:"
echo "  docker compose logs -f shim"
