#!/usr/bin/env bash
# Non-root service supervisor. Runtime data stays outside the source tree.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${LABEL_STATE_DIR:-$HOME/.local/state/label-print-assistant}"
PYTHON="${LABEL_PYTHON:-$ROOT/.venv/bin/python}"
CONFIG="${LABEL_CONFIG:-$STATE/config.json}"
mkdir -p "$STATE"

case "${1:-status}" in
  start)
    if ! command -v flock >/dev/null; then echo 'flock is required'; exit 1; fi
    if flock -n "$STATE/service.lock" true; then
      nohup setsid bash "$ROOT/linux/service.sh" supervise </dev/null >>"$STATE/supervisor.log" 2>&1 &
      for _ in {1..30}; do
        if [[ -s "$STATE/pid" ]] && kill -0 "$(cat "$STATE/pid")" 2>/dev/null; then
          echo "Supervisor started; check service.log and /api/health for readiness"; exit 0
        fi
        sleep 0.1
      done
      echo 'Supervisor did not start; see supervisor.log'; exit 1
    else
      echo 'Supervisor already running'
    fi
    ;;
  supervise)
    exec 9>"$STATE/service.lock"
    flock -n 9 || exit 0
    [[ -x "$PYTHON" && -f "$CONFIG" ]] || { echo 'Missing Python environment or configuration'; exit 1; }
    echo "$$" >"$STATE/pid"
    child=''
    cleanup() {
      trap '' TERM INT
      if [[ -n "$child" ]]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" || true; fi
      rm -f -- "$STATE/pid" "$STATE/child.pid"
      exit 0
    }
    trap cleanup TERM INT
    cd -- "$ROOT"
    while true; do
      if [[ -f "$STATE/console.log" ]] && [[ $(stat -c %s "$STATE/console.log") -gt 2097152 ]]; then
        mv -f -- "$STATE/console.log" "$STATE/console.log.1"
      fi
      "$PYTHON" -u -m webapp.server --config "$CONFIG" 9>&- >>"$STATE/console.log" 2>&1 &
      child=$!
      echo "$child" >"$STATE/child.pid"
      wait "$child" || true
      child=''
      rm -f -- "$STATE/child.pid"
      sleep 3
    done
    ;;
  stop)
    # Validate the recorded process command before signalling it (PID reuse).
    if [[ -f "$STATE/pid" ]]; then
      pid="$(cat "$STATE/pid")"
      if [[ "$pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$pid/cmdline" ]] &&
         tr '\0' '\n' <"/proc/$pid/cmdline" | grep -Fxq "$ROOT/linux/service.sh"; then
        kill -TERM "$pid"
        for _ in {1..150}; do
          [[ -e "$STATE/pid" ]] || { echo 'Stopped'; exit 0; }
          sleep 0.2
        done
        echo 'Still stopping; inspect service logs'; exit 1
      fi
    fi
    echo 'No matching supervisor running'
    ;;
  status)
    if flock -n "$STATE/service.lock" true; then echo 'Stopped'; exit 1; fi
    echo "Supervisor PID: $(cat "$STATE/pid")"
    if [[ -f "$STATE/child.pid" ]]; then echo "Service PID: $(cat "$STATE/child.pid")"; fi
    ;;
  restart)
    bash "$ROOT/linux/service.sh" stop
    bash "$ROOT/linux/service.sh" start
    ;;
  *) echo 'Usage: service.sh start|stop|restart|status'; exit 2 ;;
esac
