#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.local-run"

show_status() {
  local label="$1"
  local pid_file="$2"
  local port_file="${3:-}"

  if [[ ! -f "$pid_file" ]]; then
    echo "$label: kapali"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "$label: stale pid ($pid)"
    return
  fi

  if [[ -n "$port_file" && -f "$port_file" ]]; then
    echo "$label: acik (pid=$pid, port=$(cat "$port_file"))"
  else
    echo "$label: acik (pid=$pid)"
  fi
}

show_status "Backend" "$RUNTIME_DIR/backend.pid" "$RUNTIME_DIR/backend.port"
show_status "Frontend" "$RUNTIME_DIR/frontend.pid" "$RUNTIME_DIR/frontend.port"
show_status "Worker" "$RUNTIME_DIR/worker.pid"
