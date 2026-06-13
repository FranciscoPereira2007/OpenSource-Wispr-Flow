# Dictate — Wispr Flow clone, 100% local

Push-to-talk: segura **Fn+Space**, fala, solta → texto colado no app activo.
Tap rápido **Fn** → cola novamente o último transcript.

## Stack

- `mlx-whisper` (large-v3-turbo, fp16) em Apple Silicon — ~300-500ms p/ frase curta
- daemon Python pré-aquecido (modelo fica em RAM)
- Hammerspoon = hotkey listener
- Karabiner-Elements = remap Fn+Space → F18, Fn tap → F19 (Fn nativo não é capturável)
- launchd = daemon arranca no login
- Microfone: sempre o microfone interno do MacBook, mesmo que AirPods estejam ligados

## Instalar

### Noutro Mac

```bash
git clone https://github.com/FranciscoPereira2007/dictate-wispr-flow.git ~/dictate
cd ~/dictate
```

Depois corre:

```bash
# 1. pré-reqs
brew install uv
brew install --cask karabiner-elements hammerspoon

# 2. python deps + launchd daemon
bash ~/dictate/install.sh

# 3. hotkeys (Karabiner + Hammerspoon)
bash ~/dictate/setup_hotkeys.sh
```

Manual após o setup:

1. Karabiner-Elements → **Complex Modifications** → **Add rule** → ativa **Dictate (Wispr-style)**
2. Abre **Hammerspoon.app** uma vez → System Settings → Privacy & Security → **Accessibility** → liga Hammerspoon
3. Em System Settings → Privacy → **Microphone** → liga Python (do venv) e Hammerspoon
4. Em System Settings → Keyboard → **Use F1, F2, etc. as standard function keys** = ON (senão Fn é interceptado pelo macOS)

## Verificar

```bash
~/dictate/client.sh PING       # → PONG
~/dictate/client.sh START      # começa a gravar
~/dictate/client.sh STOP       # transcreve + copia p/ clipboard
~/dictate/client.sh PASTE      # Cmd+V
tail -f ~/dictate/logs/daemon.log
```

## Tweaks

- Trocar idioma: edita `LANG = "pt"` em `daemon.py` (`None` = auto-detect, `"en"` = inglês).
- Modelo mais leve (mais rápido, menos preciso): `mlx-community/whisper-medium-mlx` ou `whisper-small-mlx`.
- Modelo distil (só inglês, ultra rápido): `mlx-community/distil-whisper-large-v3`.
- Latência: o primeiro hit após boot demora ~3s (compile). A partir daí, <500ms.

## Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.fran.dictate.plist
rm ~/Library/LaunchAgents/com.fran.dictate.plist
rm ~/.config/karabiner/assets/complex_modifications/dictate.json
# remove o bloco DICTATE_HOOK do ~/.hammerspoon/init.lua
```
