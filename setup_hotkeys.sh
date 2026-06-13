#!/bin/bash
# Wires Karabiner (Fn+Space → F18 hold, Fn tap → F19) + Hammerspoon (F18/F19 → daemon).
set -euo pipefail

# --- Karabiner complex modification ---
KARA_DIR="$HOME/.config/karabiner/assets/complex_modifications"
mkdir -p "$KARA_DIR"
cat > "$KARA_DIR/dictate.json" <<'EOF'
{
  "title": "Dictate (Wispr-style)",
  "rules": [
    {
      "description": "Fn+Space hold → F18 (push-to-talk). Fn tap alone → F19 (paste).",
      "manipulators": [
        {
          "type": "basic",
          "from": {
            "key_code": "spacebar",
            "modifiers": { "mandatory": ["fn"] }
          },
          "to": [{ "key_code": "f18" }]
        },
        {
          "type": "basic",
          "from": {
            "key_code": "fn",
            "modifiers": { "optional": ["any"] }
          },
          "to": [{ "key_code": "fn" }],
          "to_if_alone": [{ "key_code": "f19" }]
        }
      ]
    }
  ]
}
EOF
echo "Karabiner rule escrito em $KARA_DIR/dictate.json"
echo " → abre Karabiner-Elements > Complex Modifications > Add rule > Enable 'Dictate (Wispr-style)'"

# --- Hammerspoon config ---
HS_DIR="$HOME/.hammerspoon"
mkdir -p "$HS_DIR"
HS_INIT="$HS_DIR/init.lua"
SNIPPET_MARK="-- DICTATE_HOOK"
if [ -f "$HS_INIT" ] && grep -q "$SNIPPET_MARK" "$HS_INIT"; then
  echo "Hammerspoon já tem hook dictate, skip."
else
  cat >> "$HS_INIT" <<'EOF'

-- DICTATE_HOOK
local DICTATE = os.getenv("HOME") .. "/dictate/client.sh"
local recording = false
local overlay = nil
local timer = nil
local elapsed = 0

local function killOverlay()
  if timer then timer:stop(); timer = nil end
  if overlay then overlay:delete(); overlay = nil end
end

local function showOverlay(state)
  killOverlay()
  local screen = hs.screen.mainScreen():fullFrame()
  local w, h = 220, 56
  local x = screen.x + (screen.w - w) / 2
  local y = screen.y + screen.h - h - 60
  overlay = hs.canvas.new({x = x, y = y, w = w, h = h})
  overlay:level("overlay")
  overlay:behavior({"canJoinAllSpaces", "stationary"})
  overlay[1] = {
    type = "rectangle",
    action = "fill",
    fillColor = {red = 0.07, green = 0.07, blue = 0.09, alpha = 0.92},
    roundedRectRadii = {xRadius = 18, yRadius = 18},
  }
  overlay[2] = {
    type = "circle",
    center = {x = 26, y = 28},
    radius = 6,
    fillColor = state == "rec"
      and {red = 1, green = 0.25, blue = 0.25, alpha = 1}
      or  {red = 1, green = 0.78, blue = 0.20, alpha = 1},
    action = "fill",
  }
  overlay[3] = {
    type = "text",
    text = state == "rec" and "a ouvir  0.0s" or "a transcrever…",
    textFont = "SF Pro Text",
    textSize = 15,
    textColor = {white = 1, alpha = 0.95},
    textAlignment = "left",
    frame = {x = 48, y = 17, w = 160, h = 24},
  }
  overlay:show(0.12)

  if state == "rec" then
    elapsed = 0
    timer = hs.timer.doEvery(0.1, function()
      elapsed = elapsed + 0.1
      if overlay then
        overlay[3].text = string.format("a ouvir  %.1fs", elapsed)
      end
    end)
  end
end

local function send(cmd, cb)
  hs.task.new("/bin/bash", function(_, stdout, _) if cb then cb(stdout) end end,
              {DICTATE, cmd}):start()
end

-- F18 = hold-to-talk
hs.hotkey.bind({}, "F18",
  function()  -- pressed
    if not recording then
      recording = true
      send("START")
      showOverlay("rec")
    end
  end,
  function()  -- released
    if recording then
      recording = false
      showOverlay("xcribe")
      send("STOP_PASTE", function(out)
        local txt = (out or ""):match('"text":%s*"(.-)"') or ""
        killOverlay()
        if txt ~= "" then
          hs.alert.closeAll()
          hs.alert.show("✓ " .. (txt:sub(1,60)), {radius = 12, textSize = 14}, 1.2)
        else
          hs.alert.show("∅ nada captado", 0.8)
        end
      end)
    end
  end
)

-- F19 = re-paste último transcript
hs.hotkey.bind({}, "F19", function()
  send("PASTE")
end)

hs.alert.show("Dictate pronto", 1)
EOF
  echo "Hammerspoon hook adicionado em $HS_INIT"
fi

# Reload Hammerspoon if running
if pgrep -x Hammerspoon >/dev/null; then
  open -g "hammerspoon://reload"
  echo "Hammerspoon reloaded."
else
  echo " → abre Hammerspoon.app uma vez e dá Accessibility permission."
fi

echo
echo "✅ pronto. uso:"
echo "   • Fn+Space (segura) → fala → solta → cola transcript no campo activo"
echo "   • Fn (tap rápido)   → cola novamente o último transcript"
