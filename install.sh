#!/bin/bash
# Install Wispr-Flow-style local dictation.
# 1. Python deps (uv venv) 2. launchd daemon 3. Hammerspoon hook 4. Karabiner mapping
set -euo pipefail

DICT_DIR="$HOME/dictate"
VENV="$DICT_DIR/.venv"

mkdir -p "$DICT_DIR/logs"

echo "==> creating venv"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv não instalado. instala: brew install uv"
  exit 1
fi
cd "$DICT_DIR"
uv venv "$VENV" --python 3.11
source "$VENV/bin/activate"
uv pip install --upgrade pip
uv pip install mlx-whisper sounddevice numpy

echo "==> pre-cache model (large-v3-turbo, ~1.5GB)"
python -c "import mlx_whisper, numpy as np; mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo='mlx-community/whisper-large-v3-turbo', language='pt')"

echo "==> chmod scripts"
chmod +x "$DICT_DIR"/client.sh "$DICT_DIR"/daemon.py

echo "==> launchd plist"
PLIST="$HOME/Library/LaunchAgents/com.fran.dictate.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.fran.dictate</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$DICT_DIR/daemon.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DICT_DIR/logs/stdout.log</string>
  <key>StandardErrorPath</key><string>$DICT_DIR/logs/stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "==> daemon started. teste: ~/dictate/client.sh PING (deve responder PONG após ~30s de warmup)"
echo
echo "PRÓXIMOS PASSOS MANUAIS:"
echo "  1. instala Karabiner-Elements: brew install --cask karabiner-elements"
echo "  2. instala Hammerspoon:        brew install --cask hammerspoon"
echo "  3. corre:                       ~/dictate/setup_hotkeys.sh"
