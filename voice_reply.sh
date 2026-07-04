#!/bin/bash
# Speak an agent response locally while keeping the normal text response.
# Usage:
#   ~/dictate/voice_reply.sh "Task finished. The dashboard is live."
#   echo "Task finished." | ~/dictate/voice_reply.sh
set -euo pipefail

VOICE="${DICTATE_REPLY_VOICE:-Samantha}"
RATE="${DICTATE_REPLY_RATE:-185}"
OUT_FILE="${DICTATE_REPLY_FILE:-/tmp/dictate-last-reply.txt}"

usage() {
  cat <<'EOF'
Usage:
  voice_reply.sh [--voice NAME] [--rate WPM] "text to speak"
  echo "text to speak" | voice_reply.sh
  voice_reply.sh --list-voices

Environment:
  DICTATE_REPLY_VOICE  default: Samantha
  DICTATE_REPLY_RATE   default: 185
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list-voices)
      say -v '?' | sed -n '1,120p'
      exit 0
      ;;
    --voice)
      VOICE="${2:-}"
      shift 2
      ;;
    --rate)
      RATE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -gt 0 ]]; then
  TEXT="$*"
elif [[ ! -t 0 ]]; then
  TEXT="$(cat)"
else
  usage
  exit 1
fi

TEXT="$(printf '%s' "$TEXT" | tr '\r' '\n' | sed '/^[[:space:]]*$/d')"
if [[ -z "$TEXT" ]]; then
  exit 0
fi

printf '%s\n' "$TEXT" > "$OUT_FILE"

if ! say -v "$VOICE" -r "$RATE" "$TEXT" 2>/dev/null; then
  say -r "$RATE" "$TEXT"
fi
