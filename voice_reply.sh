#!/bin/bash
# Speak an agent response locally while keeping the normal text response.
# Usage:
#   ~/dictate/voice_reply.sh "Task finished. The dashboard is live."
#   echo "Task finished." | ~/dictate/voice_reply.sh
set -euo pipefail

EN_VOICE="${DICTATE_REPLY_EN_VOICE:-Samantha}"
PT_VOICE="${DICTATE_REPLY_PT_VOICE:-Joana}"
VOICE="${DICTATE_REPLY_VOICE:-}"
RATE="${DICTATE_REPLY_RATE:-155}"
OUT_FILE="${DICTATE_REPLY_FILE:-/tmp/dictate-last-reply.txt}"
LANGUAGE="${DICTATE_REPLY_LANG:-auto}"

usage() {
  cat <<'EOF'
Usage:
  voice_reply.sh [--lang auto|en|pt] [--voice NAME] [--rate WPM] "text to speak"
  echo "text to speak" | voice_reply.sh
  voice_reply.sh --list-voices

Environment:
  DICTATE_REPLY_LANG      default: auto
  DICTATE_REPLY_EN_VOICE  default: Samantha
  DICTATE_REPLY_PT_VOICE  default: Joana
  DICTATE_REPLY_VOICE     optional override for all languages
  DICTATE_REPLY_RATE      default: 155
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
    --lang)
      LANGUAGE="${2:-auto}"
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

if [[ -z "$VOICE" ]]; then
  case "$LANGUAGE" in
    pt|pt-PT|pt_PT)
      VOICE="$PT_VOICE"
      ;;
    en|en-US|en_US)
      VOICE="$EN_VOICE"
      ;;
    auto)
      if printf '%s' "$TEXT" | grep -Eiq '(^|[[:space:]])(não|sim|isto|está|esta|para|porque|português|obrigado|feito|alterei|testar|voz|inglês)([[:space:][:punct:]]|$)|[áàâãçéêíóôõú]'; then
        VOICE="$PT_VOICE"
      else
        VOICE="$EN_VOICE"
      fi
      ;;
    *)
      VOICE="$EN_VOICE"
      ;;
  esac
fi

printf '%s\n' "$TEXT" > "$OUT_FILE"

if ! say -v "$VOICE" -r "$RATE" "$TEXT" 2>/dev/null; then
  say -r "$RATE" "$TEXT"
fi
