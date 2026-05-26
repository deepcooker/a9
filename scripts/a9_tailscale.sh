#!/usr/bin/env bash
set -euo pipefail

SOCKET="${A9_TAILSCALE_SOCKET:-/run/tailscale/tailscaled.sock}"
STATE="${A9_TAILSCALE_STATE:-/var/lib/tailscale/tailscaled.state}"
LOG="${A9_TAILSCALE_LOG:-/var/log/tailscaled.log}"
MODE="${A9_TAILSCALE_TUN:-tailscale0}"

start() {
  if command -v tailscaled >/dev/null 2>&1 && pgrep -x tailscaled >/dev/null 2>&1; then
    echo "tailscaled running"
    return 0
  fi
  if ! command -v tailscaled >/dev/null 2>&1; then
    echo "tailscaled missing" >&2
    return 1
  fi
  mkdir -p "$(dirname "$SOCKET")" "$(dirname "$STATE")" "$(dirname "$LOG")"
  rm -f "$SOCKET"
  setsid tailscaled \
    --tun="$MODE" \
    --state="$STATE" \
    --socket="$SOCKET" \
    >"$LOG" 2>&1 < /dev/null &
  sleep 2
  pgrep -a tailscaled
}

status() {
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "tailscale missing" >&2
    return 1
  fi
  tailscale --socket="$SOCKET" status --json
}

up() {
  start >/dev/null
  tailscale --socket="$SOCKET" up --ssh --accept-dns=false
}

case "${1:-status}" in
  start) start ;;
  status) status ;;
  up) up ;;
  *) echo "usage: $0 {start|status|up}" >&2; exit 2 ;;
esac
