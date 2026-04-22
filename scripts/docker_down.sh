#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
env -u OPENROUTER_API_KEY -u OPENAI_API_KEY docker compose --env-file .env down
