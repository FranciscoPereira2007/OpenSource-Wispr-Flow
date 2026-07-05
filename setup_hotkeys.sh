#!/bin/bash
# Wires Hammerspoon hotkeys + optional Karabiner Fn mapping.
# Main keyboard path: Ctrl+Space toggles dictation, Ctrl+Shift+V re-pastes last transcript.
# Optional MacBook path: Fn+Space -> F18 hold, Fn tap -> F19 paste.
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
SNIPPET_END="-- DICTATE_HOOK_END"

if [ -f "$HS_INIT" ] && grep -q -- "$SNIPPET_MARK" "$HS_INIT"; then
  cp "$HS_INIT" "$HS_INIT.dictate-backup-$(date +%Y%m%d%H%M%S)"
  awk '
    $0 == "-- DICTATE_HOOK" { skip = 1; next }
    $0 == "-- DICTATE_HOOK_END" { skip = 0; next }
    skip != 1 { print }
  ' "$HS_INIT" > "$HS_INIT.tmp"
  mv "$HS_INIT.tmp" "$HS_INIT"
  echo "Hammerspoon hook antigo removido; backup criado."
fi

cat >> "$HS_INIT" <<'EOF'

-- DICTATE_HOOK
local DICTATE = os.getenv("HOME") .. "/dictate/client.sh"
local recording = false
local overlay = nil
local timer = nil
local lastToggle = 0
local recordingStartedAt = nil
local DEBOUNCE = 0.4
local MAX_RECORDING_SECONDS = 300
local lastRecovery = 0
local idleOverlay = nil

local function killOverlay()
  if timer then timer:stop(); timer = nil end
  if overlay then overlay:delete(); overlay = nil end
end

local IDLE_W, IDLE_H = 46, 11

local function showIdle()
  if idleOverlay then idleOverlay:delete(); idleOverlay = nil end
  local screen = hs.screen.mainScreen():fullFrame()
  local x = screen.x + (screen.w - IDLE_W) / 2
  local y = screen.y + screen.h - IDLE_H - 12
  idleOverlay = hs.canvas.new({x = x, y = y, w = IDLE_W, h = IDLE_H})
  idleOverlay:level("overlay")
  idleOverlay:behavior({"canJoinAllSpaces", "stationary"})
  idleOverlay[1] = {
    type = "rectangle",
    action = "strokeAndFill",
    fillColor = {red = 0, green = 0, blue = 0, alpha = 1},
    strokeColor = {white = 0.40, alpha = 1},
    strokeWidth = 1.4,
    roundedRectRadii = {xRadius = IDLE_H/2, yRadius = IDLE_H/2},
  }
  idleOverlay:show(0.18)
end

local function hideIdle()
  if idleOverlay then
    idleOverlay:hide(0.12)
    local toDelete = idleOverlay
    idleOverlay = nil
    hs.timer.doAfter(0.15, function() toDelete:delete() end)
  end
end

local cancelRecording, stopAndPaste

local W, H = 108, 30
local BTN_R = 9
local BTN_PAD = 5
local DOT_W = 3.5
local NUM_DOTS = 7
local BAR_AREA_LEFT = BTN_PAD + BTN_R * 2 + 4
local BAR_AREA_RIGHT = W - (BTN_PAD + BTN_R * 2 + 4)
local BAR_AREA_W = BAR_AREA_RIGHT - BAR_AREA_LEFT
local LEVEL_GAIN = 0.04

local function readLevel()
  local f = io.open("/tmp/dictate.level", "r")
  if not f then return 0 end
  local v = tonumber(f:read("*l")) or 0
  f:close()
  return v
end

local levels = {}
for i = 1, NUM_DOTS do levels[i] = 0 end

local function pushLevel(v)
  for i = 1, NUM_DOTS - 1 do levels[i] = levels[i + 1] end
  levels[NUM_DOTS] = v
end

local function showOverlay(state)
  killOverlay()
  local screen = hs.screen.mainScreen():fullFrame()
  local x = screen.x + (screen.w - W) / 2
  local y = screen.y + screen.h - H - 12
  overlay = hs.canvas.new({x = x, y = y, w = W, h = H})
  overlay:level("overlay")
  overlay:behavior({"canJoinAllSpaces", "stationary"})

  overlay[1] = {
    id = "bg",
    type = "rectangle",
    action = "fill",
    fillColor = {red = 0.0, green = 0.0, blue = 0.0, alpha = 1.0},
    roundedRectRadii = {xRadius = H/2, yRadius = H/2},
  }

  overlay[2] = {
    id = "cancel",
    type = "circle",
    action = "fill",
    fillColor = {red = 0.36, green = 0.36, blue = 0.39, alpha = 1},
    center = {x = BTN_PAD + BTN_R, y = H/2},
    radius = BTN_R,
    trackMouseDown = true,
    trackMouseUp = true,
  }
  overlay[3] = {
    id = "cancel_x",
    type = "text",
    text = "✕",
    textFont = "HelveticaNeue-Bold",
    textSize = 13,
    textColor = {white = 1, alpha = 1},
    textAlignment = "center",
    frame = {x = BTN_PAD - 1, y = H/2 - 9, w = (BTN_R * 2) + 2, h = 18},
    trackMouseDown = true,
    trackMouseUp = true,
  }

  for i = 1, NUM_DOTS do
    local dx = BAR_AREA_LEFT + (i - 0.5) * (BAR_AREA_W / NUM_DOTS) - DOT_W / 2
    overlay[#overlay + 1] = {
      id = "dot" .. i,
      type = "rectangle",
      action = "fill",
      fillColor = {white = 0.95, alpha = 0.95},
      roundedRectRadii = {xRadius = DOT_W/2, yRadius = DOT_W/2},
      frame = {x = dx, y = H/2 - DOT_W/2, w = DOT_W, h = DOT_W},
    }
  end

  if state == "rec" then
    overlay[#overlay + 1] = {
      id = "stop",
      type = "circle",
      action = "fill",
      fillColor = {red = 0.95, green = 0.22, blue = 0.22, alpha = 1},
      center = {x = W - BTN_PAD - BTN_R, y = H/2},
      radius = BTN_R,
      trackMouseDown = true,
    }
    overlay[#overlay + 1] = {
      id = "stop_sq",
      type = "rectangle",
      action = "fill",
      fillColor = {white = 1, alpha = 1},
      roundedRectRadii = {xRadius = 1.5, yRadius = 1.5},
      frame = {x = W - BTN_PAD - BTN_R - 4, y = H/2 - 4, w = 8, h = 8},
      trackMouseDown = true,
    }
  else
    overlay[#overlay + 1] = {
      id = "txc",
      type = "circle",
      action = "fill",
      fillColor = {red = 1, green = 0.72, blue = 0.20, alpha = 1},
      center = {x = W - BTN_PAD - BTN_R, y = H/2},
      radius = BTN_R - 2,
    }
  end

  overlay:mouseCallback(function(canv, ev, id, mx, my)
    if ev ~= "mouseUp" and ev ~= "mouseDown" then return end
    if ev == "mouseUp" then
      if id == "cancel" or id == "cancel_x" then
        cancelRecording()
      elseif id == "stop" or id == "stop_sq" then
        stopAndPaste()
      end
    end
  end)
  overlay:canvasMouseEvents(true, true, false, false)
  overlay:clickActivating(true)
  overlay:level(hs.canvas.windowLevels.popUpMenu)

  if state == "rec" then
    local startW, startH = IDLE_W, IDLE_H
    local startX = screen.x + (screen.w - startW) / 2
    local startY = screen.y + screen.h - startH - 12
    overlay:frame({x = startX, y = startY, w = startW, h = startH})
    overlay:alpha(0.6)
    overlay:show(0)
    local steps = 12
    local i = 0
    local animTimer
    animTimer = hs.timer.doEvery(0.012, function()
      i = i + 1
      local t = i / steps
      local e = 1 - (1 - t)^3
      local cw = startW + (W - startW) * e
      local ch = startH + (H - startH) * e
      local cx = screen.x + (screen.w - cw) / 2
      local cy = screen.y + screen.h - ch - 12
      if overlay then
        overlay:frame({x = cx, y = cy, w = cw, h = ch})
        overlay:alpha(0.6 + 0.4 * e)
      end
      if i >= steps then animTimer:stop() end
    end)
  else
    overlay:show(0.12)
  end

  if state == "rec" then
    for i = 1, NUM_DOTS do levels[i] = 0 end
    timer = hs.timer.doEvery(0.06, function()
      if not overlay then return end
      local norm = math.min(1.0, readLevel() / LEVEL_GAIN)
      pushLevel(norm)
      for i = 1, NUM_DOTS do
        local lv = levels[i]
        local h = lv < 0.04 and DOT_W or DOT_W + lv * (H - 10)
        local idx = 3 + i
        if overlay[idx] then
          overlay[idx].frame = {
            x = overlay[idx].frame.x,
            y = H/2 - h/2,
            w = DOT_W,
            h = h,
          }
        end
      end
    end)
  end
end

local function send(cmd, cb)
  hs.task.new("/bin/bash", function(exitCode, stdout, stderr)
    if cb then cb(stdout or "", exitCode, stderr or "") end
  end, {DICTATE, cmd}):start()
end

local function transcriptFromJson(out)
  local ok, data = pcall(hs.json.decode, out or "")
  if ok and type(data) == "table" and type(data.text) == "string" then
    return data.text
  end
  return (out or ""):match('"text":%s*"(.-)"') or ""
end

local function finishStop(txt, daemonTimedOut)
  killOverlay()
  if txt ~= "" then
    hs.alert.closeAll()
    hs.alert.show("✓ " .. (txt:sub(1,60)), {radius = 12, textSize = 14}, 1.2)
  elseif daemonTimedOut then
    hs.alert.show("sem resposta do Dictate", {radius = 12, textSize = 14}, 1.2)
  else
    hs.alert.show("∅ nada captado", 0.8)
  end
  showIdle()
end

local pollResult
pollResult = function(deadline)
  send("BUSY", function(out)
    local busy = out or ""
    if busy:match("YES") or busy:match("TRANSCRIBING") then
      if hs.timer.secondsSinceEpoch() < deadline then
        hs.timer.doAfter(0.25, function() pollResult(deadline) end)
      else
        finishStop("", true)
      end
      return
    end

    if busy:match("NO") then
      send("RESULT", function(resultOut)
        finishStop(transcriptFromJson(resultOut), false)
      end)
      return
    end

    if hs.timer.secondsSinceEpoch() < deadline then
      hs.timer.doAfter(0.4, function() pollResult(deadline) end)
    else
      finishStop("", true)
    end
  end)
end

local escHotkey

local function recordingAge()
  if not recordingStartedAt then return 0 end
  return hs.timer.secondsSinceEpoch() - recordingStartedAt
end

local function recoverStaleRecording(message)
  local now = hs.timer.secondsSinceEpoch()
  if now - lastRecovery < 5 then return end
  lastRecovery = now

  recording = false
  recordingStartedAt = nil
  if escHotkey then escHotkey:disable() end
  send("CANCEL")
  killOverlay()
  showIdle()
  hs.alert.show(message, {radius = 12, textSize = 14}, 1.4)
end

local function startRecording()
  recording = true
  recordingStartedAt = hs.timer.secondsSinceEpoch()
  hideIdle()
  showOverlay("rec")
  if escHotkey then escHotkey:enable() end
  send("START", function(out, exitCode)
    if exitCode ~= 0 or not (out or ""):match("OK") then
      recoverStaleRecording("Dictate não arrancou")
    end
  end)
end

stopAndPaste = function()
  recording = false
  recordingStartedAt = nil
  if escHotkey then escHotkey:disable() end
  showOverlay("xcribe")
  send("STOP_PASTE", function(out)
    local response = out or ""
    if response:match("DICTATE_RESTARTED") then
      finishStop("", true)
      return
    end
    local txt = transcriptFromJson(response)
    if txt ~= "" or response:match('"text"%s*:') then
      finishStop(txt, false)
      return
    end

    pollResult(hs.timer.secondsSinceEpoch() + 60)
  end)
end

cancelRecording = function()
  recording = false
  recordingStartedAt = nil
  if escHotkey then escHotkey:disable() end
  send("CANCEL")
  killOverlay()
  hs.alert.closeAll()
  hs.alert.show("✗ cancelado", {radius = 12, textSize = 14}, 0.8)
  showIdle()
end

local function toggleRecord()
  local now = hs.timer.secondsSinceEpoch()
  if now - lastToggle < DEBOUNCE then return end
  lastToggle = now
  if not recording then startRecording() else stopAndPaste() end
end

hs.timer.doEvery(15, function()
  hs.task.new("/bin/bash", function(_, stdout, _)
    local state = stdout or ""
    if state:match("REC") then
      if not recording then
        recording = true
        recordingStartedAt = hs.timer.secondsSinceEpoch()
        showOverlay("rec")
        if escHotkey then escHotkey:enable() end
      elseif recordingAge() > MAX_RECORDING_SECONDS then
        recoverStaleRecording("Dictate ficou preso; reiniciado")
      end
    elseif state:match("IDLE") or state:match("TRANSCRIBING") then
      if recording then
        recording = false
        recordingStartedAt = nil
        if escHotkey then escHotkey:disable() end
        killOverlay()
        showIdle()
      end
    elseif recording and recordingAge() > 20 then
      recoverStaleRecording("Dictate sem resposta")
    end
  end, {DICTATE, "STATE"}):start()
end)

hs.hotkey.bind({"ctrl"}, "space", toggleRecord)

hs.hotkey.bind({"ctrl", "shift"}, "v", function()
  send("PASTE")
end)

hs.hotkey.bind({}, "F18",
  function()
    if not recording then startRecording() end
  end,
  function()
    if recording then stopAndPaste() end
  end
)

hs.hotkey.bind({}, "F19", function()
  send("PASTE")
end)

escHotkey = hs.hotkey.bind({}, "escape", cancelRecording)
escHotkey:disable()

local menubar = hs.menubar.new()
if menubar then
  menubar:setTitle("●")
  menubar:setTooltip("Dictate — clica p/ abrir dashboard")
  menubar:setMenu({
    {title = "Abrir dashboard", fn = function() hs.urlevent.openURL("http://localhost:7717") end},
    {title = "-"},
    {title = "Reload Hammerspoon", fn = function() hs.reload() end},
    {title = "Quit Hammerspoon", fn = function() os.exit() end},
  })
end

showIdle()
hs.alert.show("Dictate pronto", 1)
-- DICTATE_HOOK_END
EOF

echo "Hammerspoon hook dictate instalado em $HS_INIT"

# Reload Hammerspoon if running
if pgrep -x Hammerspoon >/dev/null; then
  open -g "hammerspoon://reload"
  echo "Hammerspoon reloaded."
else
  echo " → abre Hammerspoon.app uma vez e dá Accessibility permission."
fi

echo
echo "✅ pronto. uso:"
echo "   • Ctrl+Space         → começa/termina e cola transcript no campo activo"
echo "   • Ctrl+Shift+V       → cola novamente o último transcript"
echo "   • Fn+Space opcional  → fala enquanto seguras (via Karabiner)"
echo "   • Fn opcional        → cola novamente o último transcript (via Karabiner)"
