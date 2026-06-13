#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.local-run"
FRONTEND_LOCK="$ROOT_DIR/frontend/.next/dev/lock"

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

if [[ -f "$FRONTEND_LOCK" ]] && command -v lsof >/dev/null 2>&1; then
  frontend_lock_pids="$(lsof -t "$FRONTEND_LOCK" 2>/dev/null || true)"
  if [[ -n "${frontend_lock_pids:-}" ]]; then
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
        echo "Yetim Frontend sureci durduruldu (pid=$pid)."
      fi
    done <<< "$frontend_lock_pids"
    sleep 1
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    done <<< "$frontend_lock_pids"
  fi
fi

stop_from_pid_file "Backend" "$RUNTIME_DIR/backend.pid"

rm -f "$RUNTIME_DIR/backend.port" "$RUNTIME_DIR/frontend.port"

echo "Yerel servisler kapatildi."
