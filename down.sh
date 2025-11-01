#!/bin/bash

set -e

echo "Stopping Ollama-Anthropic shim..."

docker compose down

echo "✓ Shim stopped"
