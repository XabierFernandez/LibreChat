#!/usr/bin/env bash
set -euo pipefail

export HOME=/root
LM_HOME="${LLMSTER_HOME:-$HOME/.lmstudio}"
PORT="${LLMSTER_PORT:-1234}"
MODEL_ID="${LLMSTER_MODEL_ID:-gemma-4-e2b-it}"
CONTEXT_LENGTH="${LLMSTER_CONTEXT_LENGTH:-32768}"
GPU_OFFLOAD="${LLMSTER_GPU:-max}"
PARALLEL="${LLMSTER_PARALLEL:-4}"
EVAL_BATCH_SIZE="${LLMSTER_EVAL_BATCH_SIZE:-512}"
FLASH_ATTENTION="${LLMSTER_FLASH_ATTENTION:-true}"
OFFLOAD_KV_CACHE_TO_GPU="${LLMSTER_OFFLOAD_KV_CACHE_TO_GPU:-true}"
LOAD_ON_START="${LLMSTER_LOAD_ON_START:-true}"

mkdir -p "$LM_HOME/.internal"

clear_stale_pid_lock() {
  local lock_path="$LM_HOME/.internal/llmster-pid.lock"
  if [ -f "$lock_path" ]; then
    local pid
    pid="$(cat "$lock_path" 2>/dev/null || true)"
    if [ -n "$pid" ] && [ ! -d "/proc/$pid" ]; then
      rm -f "$lock_path"
    fi
  fi
}

clear_stale_pid_lock

LMS_BIN="$LM_HOME/bin/lms"

if [ ! -x "$LMS_BIN" ]; then
  echo "LM Studio CLI not found at $LMS_BIN" >&2
  exit 1
fi

"$LMS_BIN" daemon up --json >/tmp/llmster-daemon-up.json

for _ in $(seq 1 180); do
  if "$LMS_BIN" daemon status --json --quiet | grep -q '"status":"running"'; then
    break
  fi
  sleep 1
done

"$LMS_BIN" daemon status --json --quiet | grep -q '"status":"running"'

if ! "$LMS_BIN" server status --json --quiet 2>/dev/null | grep -q "\"running\":true"; then
  LMS_SERVER_HOST=0.0.0.0 "$LMS_BIN" server start --port "$PORT" --bind 0.0.0.0 >/tmp/llmster-server-start.log 2>&1 || {
    cat /tmp/llmster-server-start.log >&2
    exit 1
  }
fi

for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${PORT}/lmstudio-greeting" >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS "http://127.0.0.1:${PORT}/lmstudio-greeting" >/dev/null

if [ "$LOAD_ON_START" = "true" ] && [ -n "$MODEL_ID" ]; then
  echo "Preloading ${MODEL_ID} with LM Studio-compatible runtime settings..."
  cat > /tmp/llmster-load.json <<EOF
{
  "model": "${MODEL_ID}",
  "context_length": ${CONTEXT_LENGTH},
  "parallel": ${PARALLEL},
  "eval_batch_size": ${EVAL_BATCH_SIZE},
  "flash_attention": ${FLASH_ATTENTION},
  "offload_kv_cache_to_gpu": ${OFFLOAD_KV_CACHE_TO_GPU},
  "echo_load_config": true
}
EOF
  curl -fsS "http://127.0.0.1:${PORT}/api/v1/models/load" \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/llmster-load.json \
    >/tmp/llmster-load.log 2>&1 || {
      cat /tmp/llmster-load.log >&2
      exit 1
    }
  cat /tmp/llmster-load.log
fi

while true; do
  if ! curl -fsS "http://127.0.0.1:${PORT}/lmstudio-greeting" >/dev/null; then
    echo "LM Studio server is unavailable on port ${PORT}" >&2
    exit 1
  fi
  sleep 30
done
