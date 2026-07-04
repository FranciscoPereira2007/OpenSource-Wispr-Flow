#!/bin/bash
# Tiny IPC client. Usage: client.sh START | STOP | STOP_PASTE | PASTE | PING
CMD="${1:-PING}"
TIMEOUT="${DICTATE_NC_TIMEOUT:-3}"
SOCK="/tmp/dictate.sock"

send_once() {
  printf '%s\n' "$CMD" | /usr/bin/nc -U -w "$TIMEOUT" "$SOCK"
}

if send_once; then
  exit 0
fi

# If CoreAudio wedges while stopping/cancelling, the Python process can remain
# alive with an unresponsive socket. Kill/restart only for commands that are
# already trying to end a recording; STATE/PING during warmup should not loop.
case "$CMD" in
  STOP|STOP_PASTE|CANCEL)
    STATUS="$(/bin/cat /tmp/dictate.status 2>/dev/null || true)"
    if [ "$STATUS" = "recording" ] || [ "$STATUS" = "transcribing" ]; then
      /bin/launchctl kickstart -k "gui/$(/usr/bin/id -u)/com.fran.dictate" >/dev/null 2>&1 || true
      printf 'DICTATE_RESTARTED\n'
      exit 0
    fi
    ;;
esac

exit 1
