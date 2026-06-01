#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.local-run"
LOG_DIR="$RUNTIME_DIR/logs"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
BACKEND_PORT_FILE="$RUNTIME_DIR/backend.port"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
FRONTEND_PORT_FILE="$RUNTIME_DIR/frontend.port"
WORKER_PID_FILE="$RUNTIME_DIR/worker.pid"

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
WORKER_LOG="$LOG_DIR/worker.log"

mkdir -p "$LOG_DIR"

resolve_npm() {
  if [[ -n "${NPM_BIN:-}" && -x "$NPM_BIN" ]]; then
    echo "$NPM_BIN"
    return
  fi

  if command -v npm >/dev/null 2>&1; then
    command -v npm
    return
  fi

  local bundled_npm="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/npm"
  if [[ -x "$bundled_npm" ]]; then
    echo "$bundled_npm"
    return
  fi
}

resolve_node() {
  if [[ -n "${NODE_BIN:-}" && -x "$NODE_BIN" ]]; then
    echo "$NODE_BIN"
    return
  fi

  if command -v node >/dev/null 2>&1; then
    command -v node
    return
  fi

  local bundled_node="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
  if [[ -x "$bundled_node" ]]; then
    echo "$bundled_node"
    return
  fi

  echo "node"
}

NPM_CMD="$(resolve_npm || true)"
NODE_CMD="$(resolve_node)"

port_in_use() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

find_free_port() {
  local port="$1"
  while port_in_use "$port"; do
    port=$((port + 1))
  done
  echo "$port"
}

pid_is_alive() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

read_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    cat "$file"
  fi
}

cleanup_stale_pid() {
  local file="$1"
  local pid

  pid="$(read_pid_file "$file")"
  if [[ -n "${pid:-}" ]] && ! pid_is_alive "$pid"; then
    rm -f "$file"
  fi
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local timeout="${3:-30}"
  local log_file="${4:-}"
  local elapsed=0

  while (( elapsed < timeout )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "$label hazir olmadi. Log: $log_file" >&2
  return 1
}

start_detached() {
  local cwd="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  python3 - "$cwd" "$pid_file" "$log_file" "$@" <<'PY'
import os
import subprocess
import sys

cwd = sys.argv[1]
pid_file = sys.argv[2]
log_file = sys.argv[3]
cmd = sys.argv[4:]

with open(log_file, "ab", buffering=0) as log:
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=os.environ.copy(),
        stdout=log,
        stderr=log,
        start_new_session=True,
    )

with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(process.pid))
PY
}

ensure_backend_deps() {
  local stamp="$RUNTIME_DIR/backend-deps.stamp"

  if [[ ! -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
    python3 -m venv "$ROOT_DIR/backend/.venv"
  fi

  if [[ ! -f "$stamp" || "$ROOT_DIR/backend/requirements.txt" -nt "$stamp" ]]; then
    "$ROOT_DIR/backend/.venv/bin/pip" install -r "$ROOT_DIR/backend/requirements.txt"
    touch "$stamp"
  fi
}

ensure_frontend_deps() {
  local stamp="$RUNTIME_DIR/frontend-deps.stamp"

  if [[ -z "$NPM_CMD" ]]; then
    if [[ -d "$ROOT_DIR/frontend/node_modules" ]]; then
      echo "npm bulunamadi; mevcut frontend/node_modules kullaniliyor." >&2
      touch "$stamp"
      return
    fi

    echo "npm bulunamadi ve frontend/node_modules yok. Frontend bagimliliklari yuklenemiyor." >&2
    return 1
  fi

  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    (
      cd "$ROOT_DIR/frontend"
      "$NPM_CMD" install
    )
    touch "$stamp"
    return
  fi

  if [[ ! -f "$stamp" || "$ROOT_DIR/frontend/package.json" -nt "$stamp" || "$ROOT_DIR/frontend/package-lock.json" -nt "$stamp" ]]; then
    (
      cd "$ROOT_DIR/frontend"
      "$NPM_CMD" install
    )
    touch "$stamp"
  fi
}

cleanup_stale_pid "$BACKEND_PID_FILE"
cleanup_stale_pid "$FRONTEND_PID_FILE"
cleanup_stale_pid "$WORKER_PID_FILE"

ensure_backend_deps
ensure_frontend_deps

DEFAULT_DB_PATH="$ROOT_DIR/backend/local_demo_run2.db"
if [[ -f "$DEFAULT_DB_PATH" ]]; then
  LOCAL_DATABASE_PATH="${LOCAL_DATABASE_PATH:-$DEFAULT_DB_PATH}"
else
  LOCAL_DATABASE_PATH="${LOCAL_DATABASE_PATH:-$ROOT_DIR/backend/gtu_ai_local.db}"
fi

BACKEND_PORT="${BACKEND_PORT:-}"
FRONTEND_PORT="${FRONTEND_PORT:-}"

if [[ -z "$BACKEND_PORT" ]]; then
  BACKEND_PORT="$(find_free_port 8000)"
fi

if [[ -z "$FRONTEND_PORT" ]]; then
  FRONTEND_PORT="$(find_free_port 3000)"
fi

BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
DATABASE_URL="sqlite:///$LOCAL_DATABASE_PATH"
CORS_ORIGINS="http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT"

if [[ -f "$BACKEND_PID_FILE" ]]; then
  BACKEND_PID="$(read_pid_file "$BACKEND_PID_FILE")"
  BACKEND_PORT="$(cat "$BACKEND_PORT_FILE")"
  BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
else
  start_detached \
    "$ROOT_DIR/backend" \
	    "$BACKEND_PID_FILE" \
	    "$BACKEND_LOG" \
	    env \
	    -u OPENAI_API_KEY \
	    -u OPENROUTER_API_KEY \
	    APP_DOMAIN="$FRONTEND_URL" \
	    BACKEND_CORS_ORIGINS="$CORS_ORIGINS" \
	    DATABASE_URL="$DATABASE_URL" \
    REDIS_URL="redis://localhost:6379/0" \
    "$ROOT_DIR/backend/.venv/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT"
  echo "$BACKEND_PORT" > "$BACKEND_PORT_FILE"
fi

wait_for_http "$BACKEND_URL/api/health" "Backend" 30 "$BACKEND_LOG"

if [[ -f "$FRONTEND_PID_FILE" ]]; then
  FRONTEND_PID="$(read_pid_file "$FRONTEND_PID_FILE")"
  FRONTEND_PORT="$(cat "$FRONTEND_PORT_FILE")"
  FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
else
  if [[ -n "$NPM_CMD" ]]; then
    start_detached \
      "$ROOT_DIR/frontend" \
      "$FRONTEND_PID_FILE" \
      "$FRONTEND_LOG" \
      env \
      NEXT_PUBLIC_API_URL="$BACKEND_URL/api" \
      "$NPM_CMD" run dev -- --port "$FRONTEND_PORT"
  else
    start_detached \
      "$ROOT_DIR/frontend" \
      "$FRONTEND_PID_FILE" \
      "$FRONTEND_LOG" \
      env \
      NEXT_PUBLIC_API_URL="$BACKEND_URL/api" \
      "$NODE_CMD" "$ROOT_DIR/frontend/node_modules/next/dist/bin/next" dev --webpack --hostname 0.0.0.0 --port "$FRONTEND_PORT"
  fi
  echo "$FRONTEND_PORT" > "$FRONTEND_PORT_FILE"
fi

wait_for_http "$FRONTEND_URL" "Frontend" 45 "$FRONTEND_LOG"

if [[ "${LOCAL_START_WORKER:-1}" == "1" && ! -f "$WORKER_PID_FILE" ]]; then
  start_detached \
    "$ROOT_DIR/backend" \
	    "$WORKER_PID_FILE" \
	    "$WORKER_LOG" \
	    env \
	    -u OPENAI_API_KEY \
	    -u OPENROUTER_API_KEY \
	    APP_DOMAIN="$FRONTEND_URL" \
	    BACKEND_CORS_ORIGINS="$CORS_ORIGINS" \
	    DATABASE_URL="$DATABASE_URL" \
    REDIS_URL="redis://localhost:6379/0" \
    "$ROOT_DIR/backend/.venv/bin/python" -m app.worker
fi

echo "Yerel ortam hazir."
echo "Frontend: $FRONTEND_URL"
echo "Backend:  $BACKEND_URL/api/health"
echo "DB:       $LOCAL_DATABASE_PATH"
echo "Loglar:   $BACKEND_LOG ve $FRONTEND_LOG"
if [[ -f "$WORKER_PID_FILE" ]]; then
  echo "Worker:   aktif ($WORKER_LOG)"
fi
echo "Kapatmak icin: bash $ROOT_DIR/scripts/local_down.sh"
