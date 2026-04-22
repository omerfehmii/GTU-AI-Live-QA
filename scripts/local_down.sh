#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.local-run"

stop_from_pid_file() {
  local label="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    return
  fi

  local pid
  pid="$(cat "$file")"

  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    echo "$label durduruldu."
  fi

  rm -f "$file"
}

stop_from_pid_file "Worker" "$RUNTIME_DIR/worker.pid"
stop_from_pid_file "Frontend" "$RUNTIME_DIR/frontend.pid"
stop_from_pid_file "Backend" "$RUNTIME_DIR/backend.pid"

rm -f "$RUNTIME_DIR/backend.port" "$RUNTIME_DIR/frontend.port"

echo "Yerel servisler kapatildi."
