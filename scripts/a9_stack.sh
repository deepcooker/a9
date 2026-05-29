#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE_DIR="${A9_MOBILE_DIR:-/mnt/d/root/a9_mobile_agent_lab}"
HOST="${A9_HOST:-0.0.0.0}"
API_PORT="${A9_API_PORT:-8787}"
WEB_PORT="${A9_WEB_PORT:-8199}"
PUBLIC_IP="${A9_PUBLIC_IP:-10.66.64.77}"
API_BASE_URL="${A9_API_BASE_URL:-}"
STATE_DIR="${ROOT}/.a9/services"
LOG_DIR="${ROOT}/.a9/logs"

mkdir -p "$STATE_DIR" "$LOG_DIR"

pid_file() {
  printf '%s/%s.pid' "$STATE_DIR" "$1"
}

is_running() {
  local file="$1"
  [[ -f "$file" ]] && kill -0 "$(cat "$file")" 2>/dev/null
}

stop_one() {
  local name="$1"
  local file
  file="$(pid_file "$name")"
  if is_running "$file"; then
    kill -- -"$(cat "$file")" 2>/dev/null || kill "$(cat "$file")" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$file"
}

stop_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
}

port_pids() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser "${port}/tcp" 2>/dev/null || true
  fi
}

start_api() {
  stop_one control-api
  stop_port "$API_PORT"
  setsid bash -lc "cd '$ROOT' && exec python3 scripts/a9_control_api.py serve --host '$HOST' --port '$API_PORT'" \
    >"${LOG_DIR}/control-api.log" 2>&1 < /dev/null &
  echo $! >"$(pid_file control-api)"
}

start_supervisor_loop() {
  stop_one supervisor-loop
  setsid bash -lc "cd '$ROOT' && while true; do A9_IDLE_GOAL_CONTINUATION=0 python3 scripts/a9_supervisor.py run-loop --auto-next --sleep-seconds 10 --keep-going-on-error; sleep 15; done" \
    >"${LOG_DIR}/supervisor-loop.log" 2>&1 < /dev/null &
  echo $! >"$(pid_file supervisor-loop)"
}

start_mobile() {
  stop_one mobile-web
  stop_port "$WEB_PORT"
  if [[ -n "$API_BASE_URL" ]]; then
    setsid bash -lc "cd '$MOBILE_DIR' && exec env EXPO_PUBLIC_A9_API_BASE_URL='$API_BASE_URL' CI=1 npx expo start --web --port '$WEB_PORT' --host lan" \
      >"${LOG_DIR}/mobile-web.log" 2>&1 < /dev/null &
  else
    setsid bash -lc "cd '$MOBILE_DIR' && exec env CI=1 npx expo start --web --port '$WEB_PORT' --host lan" \
      >"${LOG_DIR}/mobile-web.log" 2>&1 < /dev/null &
  fi
  echo $! >"$(pid_file mobile-web)"
}

start_node_worker() {
  stop_one node-worker
  setsid bash -lc "cd '$ROOT' && exec python3 scripts/a9_node.py command-work-loop --block-ms 5000 --timeout 10 --sleep-seconds 1 --min-idle-ms 30000" \
    >"${LOG_DIR}/node-worker.log" 2>&1 < /dev/null &
  echo $! >"$(pid_file node-worker)"
}

start_recovery_loop() {
  stop_one recovery-loop
  setsid bash -lc "cd '$ROOT' && exec python3 scripts/a9_recovery_loop.py --controller-url 'http://127.0.0.1:${API_PORT}' --interval-seconds 60 --timeout 10 --max-actions 3" \
    >"${LOG_DIR}/recovery-loop.log" 2>&1 < /dev/null &
  echo $! >"$(pid_file recovery-loop)"
}

status_one() {
  local name="$1"
  local port="$2"
  local file
  local pids
  file="$(pid_file "$name")"
  if [[ "$port" == "0" ]]; then
    pids=""
  else
    pids="$(port_pids "$port" | xargs || true)"
  fi
  if is_running "$file"; then
    printf '%s running pid=%s\n' "$name" "$(cat "$file")"
  elif [[ -n "$pids" ]]; then
    printf '%s running port=%s pids=%s\n' "$name" "$port" "$pids"
  else
    printf '%s stopped\n' "$name"
  fi
}

case "${1:-status}" in
  start)
    start_api
    start_supervisor_loop
    start_node_worker
    start_recovery_loop
    start_mobile
    ;;
  stop)
    stop_one mobile-web
    stop_one recovery-loop
    stop_one node-worker
    stop_one supervisor-loop
    stop_one control-api
    stop_port "$WEB_PORT"
    stop_port "$API_PORT"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    status_one control-api "$API_PORT"
    status_one supervisor-loop 0
    status_one node-worker 0
    status_one recovery-loop 0
    status_one mobile-web "$WEB_PORT"
    ;;
  logs)
    tail -n "${2:-80}" "${LOG_DIR}/control-api.log" "${LOG_DIR}/supervisor-loop.log" "${LOG_DIR}/node-worker.log" "${LOG_DIR}/recovery-loop.log" "${LOG_DIR}/mobile-web.log"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
