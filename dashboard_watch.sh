#!/bin/bash
set -u

URL="http://127.0.0.1:7717/"
LABEL="com.fran.dictate"
STATUS_FILE="$HOME/dictate/.dashboard-watch.status"
LOG_FILE="$HOME/dictate/logs/dashboard-watch.log"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$HOME/dictate/logs"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

previous_status() {
  if [ -f "$STATUS_FILE" ]; then
    cat "$STATUS_FILE"
  else
    printf 'unknown'
  fi
}

write_status() {
  printf '%s' "$1" > "$STATUS_FILE"
}

dashboard_up() {
  curl -fsS --max-time 2 "$URL" >/dev/null 2>&1
}

open_dashboard() {
  open -a "Google Chrome" "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1 || true
}

prev="$(previous_status)"

if dashboard_up; then
  write_status "up"
  if [ "$prev" = "down" ]; then
    log "dashboard recovered; opening dashboard"
    open_dashboard
  elif [ "$prev" = "unknown" ]; then
    log "dashboard available; opening dashboard"
    open_dashboard
  else
    log "dashboard up"
  fi
  exit 0
fi

write_status "down"
log "dashboard down; kickstarting $LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

sleep 5
if dashboard_up; then
  write_status "up"
  log "dashboard up after kickstart; opening dashboard"
  open_dashboard
else
  log "dashboard still down after kickstart"
fi
