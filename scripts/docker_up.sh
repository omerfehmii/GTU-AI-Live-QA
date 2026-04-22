#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

env -u OPENROUTER_API_KEY -u OPENAI_API_KEY docker compose --env-file .env up -d --build

echo
echo "GTU AI Live QA ayakta."
echo "Public UI:  http://localhost"
echo "Direct UI:  http://localhost:3000"
echo "API:        http://localhost:8000/api/health"
echo "Admin UI:   http://localhost/admin"
echo "Archive:    backend/data/source_archive"
