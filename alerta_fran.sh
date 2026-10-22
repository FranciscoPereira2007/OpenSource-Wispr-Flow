#!/bin/bash
# Aviso curto ao Fran só quando é preciso ele fazer algo (login, 2FA, aceitar). Voz de mulher (Joana, pt-PT).
# Uso: ~/dictate/alerta_fran.sh "Faz login no TikTok."
[ -f ~/dictate/.mute ] && exit 0
V=Joana; say -v '?' | grep -q "Joana (Premium)" && V="Joana (Premium)"; say -v '?' | grep -q "Joana (Enhanced)" && V="Joana (Enhanced)"
say -v "$V" -r 170 "$*"
osascript -e "display notification \"$*\" with title \"Forge: preciso de ti\" sound name \"Glass\"" 2>/dev/null
