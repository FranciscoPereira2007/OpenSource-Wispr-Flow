#!/bin/bash
# Tiny IPC client. Usage: client.sh START | STOP | STOP_PASTE | PASTE | PING
CMD="${1:-PING}"
TIMEOUT="${DICTATE_NC_TIMEOUT:-10}"
printf '%s\n' "$CMD" | /usr/bin/nc -U -w "$TIMEOUT" /tmp/dictate.sock
