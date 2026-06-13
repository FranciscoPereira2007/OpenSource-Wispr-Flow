"""Tiny HTTP dashboard for dictate history. Imported by daemon, runs in background thread."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def make_handler(history_path: Path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/" or url.path == "/index.html":
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            elif url.path == "/api/history":
                entries = []
                if history_path.exists():
                    with open(history_path) as f:
                        for line in f:
                            try:
                                entries.append(json.loads(line))
                            except Exception:
                                pass
                entries.reverse()
                self._send(200, json.dumps(entries).encode(), "application/json")
            elif url.path == "/api/stats":
                total_words = 0
                total_secs = 0.0
                count = 0
                if history_path.exists():
                    with open(history_path) as f:
                        for line in f:
                            try:
                                e = json.loads(line)
                                total_words += e.get("words", 0)
                                total_secs += e.get("duration", 0)
                                count += 1
                            except Exception:
                                pass
                wpm = round(total_words / (total_secs / 60), 0) if total_secs > 0 else 0
                stats = {
                    "total_words": total_words,
                    "total_seconds": round(total_secs, 1),
                    "transcripts": count,
                    "wpm": wpm,
                }
                self._send(200, json.dumps(stats).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_DELETE(self):
            url = urlparse(self.path)
            if url.path == "/api/history":
                qs = parse_qs(url.query)
                ts = qs.get("ts", [None])[0]
                if ts:
                    # remove single entry by ts
                    keep = []
                    if history_path.exists():
                        with open(history_path) as f:
                            for line in f:
                                try:
                                    e = json.loads(line)
                                    if str(e.get("ts")) != ts:
                                        keep.append(line)
                                except Exception:
                                    keep.append(line)
                    with open(history_path, "w") as f:
                        f.writelines(keep)
                    self._send(200, b"ok", "text/plain")
                else:
                    # clear all
                    if history_path.exists():
                        history_path.unlink()
                    self._send(200, b"cleared", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

    return H


def start(history_path: Path, port: int = 7717) -> None:
    handler = make_handler(history_path)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()


INDEX_HTML = """<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<title>Dictate</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --bg: #0c0c0e;
  --panel: #16161a;
  --panel2: #1d1d22;
  --text: #f0f0f2;
  --muted: #8a8a92;
  --accent: #ff5544;
  --border: #2a2a30;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "SF Pro Text", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
}
.app { display: grid; grid-template-columns: 240px 1fr 280px; min-height: 100vh; }
.side { background: var(--panel); border-right: 1px solid var(--border); padding: 22px 16px; }
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; }
.brand-dot { width: 10px; height: 10px; border-radius: 5px; background: var(--accent); box-shadow: 0 0 12px var(--accent); }
.brand-name { font-weight: 600; font-size: 16px; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px; color: var(--muted);
  cursor: pointer; font-size: 14px; user-select: none;
}
.nav-item.active { background: var(--panel2); color: var(--text); }
.main { padding: 32px 40px; overflow-y: auto; max-height: 100vh; }
.h1 { font-size: 26px; font-weight: 600; margin: 0 0 6px; }
.h-sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.empty {
  background: var(--panel); border: 1px dashed var(--border);
  border-radius: 12px; padding: 60px 20px; text-align: center; color: var(--muted);
}
.day { font-size: 11px; font-weight: 600; color: var(--muted); letter-spacing: 1.5px; margin: 28px 0 10px; }
.row {
  display: grid; grid-template-columns: 80px 1fr auto; gap: 16px; align-items: start;
  padding: 16px; background: var(--panel); border-radius: 10px; border: 1px solid var(--border);
  margin-bottom: 8px;
}
.row:hover { background: var(--panel2); }
.time { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; padding-top: 2px; }
.text { font-size: 14px; line-height: 1.55; word-break: break-word; }
.actions { display: flex; gap: 6px; opacity: 0; transition: opacity 0.15s; }
.row:hover .actions { opacity: 1; }
.btn {
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; width: 30px; height: 28px; cursor: pointer; font-size: 13px;
  display: inline-flex; align-items: center; justify-content: center;
}
.btn:hover { color: var(--text); border-color: var(--muted); }
.btn.danger:hover { color: var(--accent); border-color: var(--accent); }

.stats { padding: 32px 24px; }
.stat { margin-bottom: 28px; }
.stat-num { font-size: 36px; font-weight: 600; line-height: 1; }
.stat-lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px; margin-top: 4px; }
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: var(--panel2); border: 1px solid var(--border); padding: 8px 16px;
  border-radius: 8px; font-size: 13px; opacity: 0; transition: opacity 0.18s;
  pointer-events: none;
}
.toast.show { opacity: 1; }
.clear-btn {
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12px;
  margin-top: 12px;
}
.clear-btn:hover { color: var(--accent); border-color: var(--accent); }
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">
      <div class="brand-dot"></div>
      <div class="brand-name">Dictate</div>
    </div>
    <div class="nav-item active">📋 Histórico</div>
    <div class="nav-item">📊 Estatísticas</div>
  </aside>

  <main class="main">
    <h1 class="h1">Olá, Francisco</h1>
    <p class="h-sub">Tap <b>Fn+Space</b> em qualquer app para começar a ditar.</p>
    <div id="list"></div>
  </main>

  <aside class="stats">
    <div class="stat">
      <div class="stat-num" id="s-words">—</div>
      <div class="stat-lbl">total words</div>
    </div>
    <div class="stat">
      <div class="stat-num" id="s-wpm">—</div>
      <div class="stat-lbl">wpm médio</div>
    </div>
    <div class="stat">
      <div class="stat-num" id="s-count">—</div>
      <div class="stat-lbl">transcripts</div>
    </div>
    <button class="clear-btn" onclick="clearAll()">Apagar tudo</button>
  </aside>
</div>
<div class="toast" id="toast"></div>

<script>
function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('pt-PT', {hour: '2-digit', minute: '2-digit'});
}
function fmtDay(iso) {
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  const fmt = d.toDateString();
  if (fmt === today.toDateString()) return 'HOJE';
  if (fmt === y.toDateString()) return 'ONTEM';
  return d.toLocaleDateString('pt-PT', {weekday:'long', day:'numeric', month:'long'}).toUpperCase();
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400);
}
async function copyText(txt) {
  await navigator.clipboard.writeText(txt);
  toast('copiado');
}
async function delEntry(ts) {
  await fetch('/api/history?ts=' + ts, {method: 'DELETE'});
  load();
}
async function clearAll() {
  if (!confirm('Apagar todos os transcripts?')) return;
  await fetch('/api/history', {method: 'DELETE'});
  load();
}
async function load() {
  const [hist, stats] = await Promise.all([
    fetch('/api/history').then(r => r.json()),
    fetch('/api/stats').then(r => r.json()),
  ]);
  document.getElementById('s-words').textContent = stats.total_words.toLocaleString('pt-PT');
  document.getElementById('s-wpm').textContent = stats.wpm;
  document.getElementById('s-count').textContent = stats.transcripts;

  const list = document.getElementById('list');
  if (!hist.length) {
    list.innerHTML = '<div class="empty">Ainda não há transcripts.<br>Tap <b>Fn+Space</b> para começar.</div>';
    return;
  }
  let html = '', lastDay = '';
  for (const e of hist) {
    const day = fmtDay(e.iso);
    if (day !== lastDay) {
      html += `<div class="day">${day}</div>`;
      lastDay = day;
    }
    const safe = e.text.replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
    html += `
      <div class="row">
        <div class="time">${fmtTime(e.iso)}</div>
        <div class="text">${safe}</div>
        <div class="actions">
          <button class="btn" onclick='copyText(${JSON.stringify(e.text)})' title="Copiar">⎘</button>
          <button class="btn danger" onclick="delEntry(${e.ts})" title="Apagar">✕</button>
        </div>
      </div>`;
  }
  list.innerHTML = html;
}
load();
setInterval(load, 5000);
</script>
</body>
</html>
"""
