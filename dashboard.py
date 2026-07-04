"""Local HTTP dashboard for Dictate history and learning metrics."""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*")

PT_MARKERS = {
    "a",
    "ao",
    "aos",
    "as",
    "com",
    "como",
    "da",
    "das",
    "de",
    "dei",
    "depois",
    "diz",
    "do",
    "dos",
    "e",
    "em",
    "entao",
    "então",
    "era",
    "essa",
    "esse",
    "esta",
    "está",
    "eu",
    "fazer",
    "foi",
    "isso",
    "isto",
    "lá",
    "mais",
    "mas",
    "me",
    "mesmo",
    "meter",
    "muito",
    "na",
    "não",
    "no",
    "nos",
    "nós",
    "o",
    "obrigado",
    "ok",
    "olha",
    "os",
    "ou",
    "para",
    "pela",
    "pelo",
    "por",
    "porque",
    "preciso",
    "quando",
    "que",
    "queres",
    "se",
    "sem",
    "ser",
    "só",
    "também",
    "tem",
    "tenho",
    "tu",
    "um",
    "uma",
    "vais",
    "ver",
    "vou",
}

EN_MARKERS = {
    "a",
    "about",
    "add",
    "after",
    "ai",
    "and",
    "app",
    "are",
    "as",
    "at",
    "because",
    "build",
    "can",
    "check",
    "could",
    "do",
    "does",
    "fix",
    "for",
    "from",
    "get",
    "have",
    "how",
    "i",
    "if",
    "image",
    "in",
    "is",
    "it",
    "keep",
    "make",
    "me",
    "need",
    "not",
    "of",
    "on",
    "open",
    "please",
    "prompt",
    "screen",
    "server",
    "should",
    "simulator",
    "slide",
    "that",
    "the",
    "this",
    "to",
    "use",
    "what",
    "when",
    "with",
    "you",
}

CATEGORY_KEYWORDS = {
    "code": {
        "label": "Code",
        "color": "#171717",
        "words": {
            "api",
            "app",
            "build",
            "bug",
            "code",
            "codex",
            "database",
            "deploy",
            "endpoint",
            "expo",
            "fix",
            "github",
            "ios",
            "logs",
            "metro",
            "react",
            "repo",
            "server",
            "simulator",
            "supabase",
            "xcode",
        },
    },
    "content": {
        "label": "Content",
        "color": "#7c3aed",
        "words": {
            "caption",
            "content",
            "edit",
            "foto",
            "gerar",
            "hook",
            "image",
            "imagem",
            "prompt",
            "reel",
            "slide",
            "slideshow",
            "tiktok",
            "video",
            "vídeo",
        },
    },
    "business": {
        "label": "Business",
        "color": "#0f766e",
        "words": {
            "client",
            "cliente",
            "contract",
            "contrato",
            "crm",
            "email",
            "invoice",
            "lead",
            "meeting",
            "proposal",
            "proposta",
            "venda",
            "zyra",
        },
    },
    "english": {
        "label": "English",
        "color": "#ea580c",
        "words": {
            "english",
            "frase",
            "frases",
            "grammar",
            "inglês",
            "language",
            "learn",
            "palavra",
            "phrase",
            "speak",
            "word",
        },
    },
    "fitness": {
        "label": "Fitness",
        "color": "#16a34a",
        "words": {
            "calorias",
            "calories",
            "exercise",
            "fitness",
            "food",
            "meal",
            "nutrition",
            "repz",
            "treino",
            "workout",
        },
    },
}

SUGGESTED_PHRASES = [
    "Can you rewrite this in natural English?",
    "Keep the same aspect ratio as the original.",
    "The app is stuck on the splash screen.",
    "Check if the development server is running.",
    "Make the prompt more precise and easier to follow.",
]


def _strip_accents_for_markers(text: str) -> str:
    table = str.maketrans("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ", "aaaaeeioooucAAAAEEIOOOUC")
    return text.translate(table).lower()


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in WORD_RE.finditer(text)]


def analyze_text(text: str) -> dict:
    tokens = _tokens(text)
    total = len(tokens)
    if not total:
        return {
            "language": "unknown",
            "en_words": 0,
            "pt_words": 0,
            "unknown_words": 0,
            "en_pct": 0,
            "pt_pct": 0,
            "category": "general",
            "category_label": "General",
            "category_color": "#737373",
        }

    normalized = [_strip_accents_for_markers(t) for t in tokens]
    en_hits = 0
    pt_hits = 0
    for raw, norm in zip(tokens, normalized):
        has_pt_chars = bool(re.search(r"[áàâãéêíóôõúç]", raw))
        if norm in EN_MARKERS or raw in EN_MARKERS:
            en_hits += 1
        if raw in PT_MARKERS or norm in PT_MARKERS or has_pt_chars:
            pt_hits += 1

    known = max(en_hits + pt_hits, 1)
    en_words = round(total * (en_hits / known)) if en_hits else 0
    pt_words = round(total * (pt_hits / known)) if pt_hits else 0
    if en_words + pt_words > total:
        overflow = en_words + pt_words - total
        if en_words >= pt_words:
            en_words -= overflow
        else:
            pt_words -= overflow
    unknown_words = max(total - en_words - pt_words, 0)
    en_pct = round((en_words / total) * 100)
    pt_pct = round((pt_words / total) * 100)

    if en_pct >= 70:
        language = "en"
    elif pt_pct >= 70:
        language = "pt"
    elif en_words and pt_words:
        language = "mixed"
    else:
        language = "unknown"

    category = "general"
    category_score = 0
    token_set = set(tokens) | set(normalized)
    for key, cfg in CATEGORY_KEYWORDS.items():
        score = len(token_set & cfg["words"])
        if score > category_score:
            category = key
            category_score = score

    if category == "general":
        category_label = "General"
        category_color = "#737373"
    else:
        cfg = CATEGORY_KEYWORDS[category]
        category_label = cfg["label"]
        category_color = cfg["color"]

    return {
        "language": language,
        "en_words": en_words,
        "pt_words": pt_words,
        "unknown_words": unknown_words,
        "en_pct": en_pct,
        "pt_pct": pt_pct,
        "category": category,
        "category_label": category_label,
        "category_color": category_color,
    }


def _parse_iso(value: str | None, fallback_ts: float | None = None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    if fallback_ts:
        return datetime.fromtimestamp(float(fallback_ts))
    return datetime.now()


def _read_entries(history_path: Path) -> list[dict]:
    entries = []
    if not history_path.exists():
        return entries
    with open(history_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except Exception:
                continue
            text = str(entry.get("text", ""))
            entry["words"] = int(entry.get("words") or len(text.split()))
            entry["duration"] = float(entry.get("duration") or 0)
            entry["meta"] = entry.get("meta") or analyze_text(text)
            entries.append(entry)
    return entries


def _write_entries(history_path: Path, entries: list[dict]) -> None:
    with open(history_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _entry_date(entry: dict) -> datetime:
    return _parse_iso(entry.get("iso"), entry.get("ts"))


def _sentence_candidates(entries: list[dict]) -> list[str]:
    today = datetime.now().date()
    candidates = []
    for entry in entries:
        if _entry_date(entry).date() != today:
            continue
        meta = entry.get("meta") or {}
        if meta.get("language") not in {"en", "mixed"}:
            continue
        parts = re.split(r"(?<=[.!?])\s+|\n+", entry.get("text", ""))
        for part in parts:
            phrase = " ".join(part.split())
            words = phrase.split()
            if 4 <= len(words) <= 22:
                candidates.append(phrase)
    seen = set()
    unique = []
    for phrase in candidates:
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            unique.append(phrase)
    return (unique + SUGGESTED_PHRASES)[:5]


def build_stats(entries: list[dict]) -> dict:
    now = datetime.now()
    today = now.date()
    week_start = today - timedelta(days=6)

    total_words = 0
    total_secs = 0.0
    today_words = 0
    today_secs = 0.0
    today_count = 0
    today_en = 0
    today_pt = 0
    today_unknown = 0
    week_words = 0
    category_words = defaultdict(int)
    category_counts = defaultdict(int)
    daily = {week_start + timedelta(days=i): {"words": 0, "en": 0, "pt": 0} for i in range(7)}

    active_days = set()
    for entry in entries:
        words = int(entry.get("words") or 0)
        duration = float(entry.get("duration") or 0)
        meta = entry.get("meta") or analyze_text(entry.get("text", ""))
        dt = _entry_date(entry)
        day = dt.date()

        total_words += words
        total_secs += duration
        if words:
            active_days.add(day)

        category = meta.get("category", "general")
        category_words[category] += words
        category_counts[category] += 1

        if week_start <= day <= today:
            week_words += words
            daily[day]["words"] += words
            daily[day]["en"] += int(meta.get("en_words") or 0)
            daily[day]["pt"] += int(meta.get("pt_words") or 0)

        if day == today:
            today_words += words
            today_secs += duration
            today_count += 1
            today_en += int(meta.get("en_words") or 0)
            today_pt += int(meta.get("pt_words") or 0)
            today_unknown += int(meta.get("unknown_words") or 0)

    streak = 0
    cursor = today
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    category_total = sum(category_words.values()) or 1
    categories = []
    all_category_keys = set(category_words) | set(CATEGORY_KEYWORDS) | {"general"}
    for key in all_category_keys:
        if key == "general":
            label = "General"
            color = "#737373"
        else:
            cfg = CATEGORY_KEYWORDS.get(key, {})
            label = cfg.get("label", key.title())
            color = cfg.get("color", "#737373")
        categories.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "words": category_words.get(key, 0),
                "count": category_counts.get(key, 0),
                "pct": round((category_words.get(key, 0) / category_total) * 100),
            }
        )
    categories.sort(key=lambda x: x["words"], reverse=True)

    today_total_known = max(today_en + today_pt + today_unknown, 1)
    total_wpm = round(total_words / (total_secs / 60)) if total_secs > 0 else 0
    today_wpm = round(today_words / (today_secs / 60)) if today_secs > 0 else 0

    return {
        "total_words": total_words,
        "total_seconds": round(total_secs, 1),
        "transcripts": len(entries),
        "wpm": total_wpm,
        "today": {
            "words": today_words,
            "seconds": round(today_secs, 1),
            "transcripts": today_count,
            "wpm": today_wpm,
            "en_words": today_en,
            "pt_words": today_pt,
            "unknown_words": today_unknown,
            "en_pct": round((today_en / today_total_known) * 100),
            "pt_pct": round((today_pt / today_total_known) * 100),
            "unknown_pct": round((today_unknown / today_total_known) * 100),
        },
        "week": {"words": week_words, "streak": streak},
        "daily": [
            {
                "date": day.isoformat(),
                "label": day.strftime("%a"),
                "words": data["words"],
                "en": data["en"],
                "pt": data["pt"],
            }
            for day, data in daily.items()
        ],
        "categories": categories,
        "phrase_bank": _sentence_candidates(entries),
    }


def make_handler(history_path: Path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict | list):
            self._send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json")

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain")

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in {"/", "/index.html"}:
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            elif url.path == "/api/history":
                entries = _read_entries(history_path)
                entries.reverse()
                self._json(200, entries)
            elif url.path == "/api/stats":
                self._json(200, build_stats(_read_entries(history_path)))
            else:
                self._send(404, b"not found", "text/plain")

        def do_PUT(self):
            url = urlparse(self.path)
            if url.path != "/api/history":
                self._send(404, b"not found", "text/plain")
                return

            ts = parse_qs(url.query).get("ts", [None])[0]
            if not ts:
                self._json(400, {"error": "missing ts"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                text = str(payload.get("text", "")).strip()
            except Exception:
                self._json(400, {"error": "invalid json"})
                return

            entries = _read_entries(history_path)
            updated = False
            for entry in entries:
                if str(entry.get("ts")) == str(ts):
                    entry["text"] = text
                    entry["words"] = len(text.split())
                    entry["meta"] = analyze_text(text)
                    entry["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    updated = True
                    break
            if not updated:
                self._json(404, {"error": "not found"})
                return
            _write_entries(history_path, entries)
            self._json(200, {"ok": True})

        def do_DELETE(self):
            url = urlparse(self.path)
            if url.path != "/api/history":
                self._send(404, b"not found", "text/plain")
                return

            ts = parse_qs(url.query).get("ts", [None])[0]
            if ts:
                entries = [e for e in _read_entries(history_path) if str(e.get("ts")) != str(ts)]
                _write_entries(history_path, entries)
                self._send(200, b"ok", "text/plain")
            else:
                if history_path.exists():
                    history_path.unlink()
                self._send(200, b"cleared", "text/plain")

    return H


def start(history_path: Path, port: int = 7717) -> None:
    handler = make_handler(history_path)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dictate Flow</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --bg: #f8f7f4;
  --surface: #ffffff;
  --surface-soft: #f0eee8;
  --ink: #171717;
  --muted: #68645d;
  --line: #e5e1d8;
  --line-strong: #d4cec2;
  --accent: #7c3aed;
  --accent-soft: #efe7ff;
  --good: #16a34a;
  --warn: #ea580c;
  --danger: #dc2626;
  --shadow: 0 24px 70px rgba(30, 24, 12, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
  letter-spacing: 0;
  -webkit-font-smoothing: antialiased;
}
button, textarea { font: inherit; }
.app { display: grid; grid-template-columns: 208px minmax(0, 1fr); min-height: 100vh; }
.side {
  padding: 20px 12px;
  background: #f3f1ec;
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.brand { display: flex; align-items: center; gap: 8px; padding: 0 2px 12px; }
.mark { display: inline-flex; gap: 2px; align-items: end; height: 22px; }
.mark i { display: block; width: 3px; background: var(--ink); border-radius: 3px; }
.mark i:nth-child(1) { height: 13px; }
.mark i:nth-child(2) { height: 19px; }
.mark i:nth-child(3) { height: 10px; }
.mark i:nth-child(4) { height: 16px; }
.brand-name { font-size: 19px; font-weight: 760; }
.pill {
  font-size: 12px;
  font-weight: 760;
  padding: 4px 8px;
  background: var(--accent-soft);
  color: #4c1d95;
  border-radius: 8px;
}
.nav { display: grid; gap: 4px; }
.nav-item {
  border: 0;
  background: transparent;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  text-align: left;
  cursor: pointer;
}
.nav-item.active { background: #e9e6de; }
.nav-ico { width: 18px; text-align: center; }
.trial-card {
  margin-top: 20px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  box-shadow: 0 10px 30px rgba(30,24,12,.04);
  cursor: pointer;
}
.trial-card:hover { border-color: var(--line-strong); background: #fff; }
.trial-title { font-weight: 760; margin-bottom: 6px; }
.mini-bar { height: 6px; background: #ebe7df; border-radius: 999px; overflow: hidden; margin: 10px 0; }
.mini-bar span { display: block; height: 100%; width: 0; background: var(--accent); border-radius: inherit; }
.side-foot { margin-top: auto; color: var(--muted); font-size: 12px; line-height: 1.4; padding: 0 8px; }
.shell { padding: 48px clamp(24px, 6vw, 96px) 32px; overflow: auto; max-height: 100vh; }
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 26px;
}
h1 { margin: 0; font-size: 25px; line-height: 1.1; }
.top-stats { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  background: #f2f0eb;
  border-radius: 999px;
  padding: 7px 11px;
  font-weight: 760;
  font-size: 13px;
  box-shadow: 0 6px 18px rgba(30,24,12,.04);
}
.challenge {
  display: grid;
  grid-template-columns: minmax(0,1fr) 76px;
  gap: 18px;
  align-items: center;
  background: #ece9e1;
  border-radius: 22px;
  padding: 18px 24px;
  margin-bottom: 22px;
}
.challenge h2 { margin: 0 0 6px; font-size: 18px; }
.challenge p { margin: 0; color: #494640; font-size: 14px; }
.progress { margin-top: 14px; height: 4px; background: #d6d0c5; border-radius: 999px; overflow: hidden; }
.progress span { display: block; height: 100%; width: 0; background: var(--accent); border-radius: inherit; }
.progress-label { margin-top: 8px; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.logo-tile {
  width: 76px;
  height: 76px;
  border-radius: 18px;
  background: #171717;
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 28px;
}
.metrics {
  display: grid;
  grid-template-columns: 1.2fr .8fr;
  gap: 16px;
  margin-bottom: 28px;
}
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
}
.panel.pad { padding: 18px; }
.panel-title { margin: 0 0 14px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.language-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.metric-card { background: #faf9f6; border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.metric-num { font-size: 32px; font-weight: 820; line-height: 1; }
.metric-label { margin-top: 7px; color: var(--muted); font-size: 12px; }
.split-bar {
  display: flex;
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: #ebe7df;
  margin-top: 14px;
}
.split-en { background: #2563eb; }
.split-pt { background: #16a34a; }
.split-unknown { background: #d6d3d1; }
.donut-wrap { display: grid; grid-template-columns: 132px 1fr; gap: 18px; align-items: center; }
.donut {
  width: 132px;
  height: 132px;
  border-radius: 50%;
  background: conic-gradient(#737373 0deg 360deg);
  position: relative;
}
.donut:after {
  content: "";
  position: absolute;
  inset: 24px;
  border-radius: 50%;
  background: var(--surface);
}
.legend { display: grid; gap: 8px; }
.legend-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; }
.legend-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
.history-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin: 8px 0 10px;
}
.history-head h2 { margin: 0; font-size: 16px; }
.clear-btn {
  background: transparent;
  border: 1px solid var(--line-strong);
  color: var(--muted);
  border-radius: 8px;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 12px;
}
.clear-btn:hover { color: var(--danger); border-color: var(--danger); }
.day { font-size: 11px; font-weight: 820; color: var(--muted); letter-spacing: .12em; margin: 20px 0 10px; }
.row {
  display: grid;
  grid-template-columns: 78px minmax(0,1fr) auto;
  gap: 16px;
  align-items: start;
  background: rgba(255,255,255,.72);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 8px;
}
.row:hover { background: #fff; }
.time { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; padding-top: 3px; }
.text { font-size: 14px; line-height: 1.55; word-break: break-word; white-space: pre-wrap; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tag { display: inline-flex; align-items: center; gap: 5px; border-radius: 999px; padding: 4px 8px; background: #f4f1eb; color: var(--muted); font-size: 11px; font-weight: 700; }
.actions { display: flex; gap: 6px; opacity: .24; transition: opacity .15s; }
.row:hover .actions { opacity: 1; }
.btn {
  width: 31px;
  height: 29px;
  border-radius: 8px;
  border: 1px solid var(--line-strong);
  background: #fff;
  color: #4a4741;
  cursor: pointer;
}
.btn:hover { border-color: #7d756a; }
.btn.danger:hover { color: var(--danger); border-color: var(--danger); }
.editor { display: grid; gap: 10px; }
.editor textarea {
  width: 100%;
  min-height: 130px;
  resize: vertical;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  padding: 12px;
  background: #fff;
  color: var(--ink);
  line-height: 1.5;
}
.editor-actions { display: flex; gap: 8px; }
.primary {
  border: 0;
  background: var(--ink);
  color: #fff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-weight: 740;
}
.secondary {
  border: 1px solid var(--line-strong);
  background: #fff;
  color: var(--ink);
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
}
.empty {
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  padding: 52px 18px;
  text-align: center;
  color: var(--muted);
}
.phrase-bank { display: grid; gap: 8px; }
.phrase {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  background: #faf9f6;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 10px 12px;
  font-size: 13px;
}
.phrase button {
  flex: 0 0 auto;
  border: 0;
  background: #ede9fe;
  color: #4c1d95;
  border-radius: 7px;
  padding: 6px 8px;
  cursor: pointer;
  font-weight: 760;
}
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #171717;
  color: #fff;
  padding: 9px 14px;
  border-radius: 999px;
  font-size: 13px;
  opacity: 0;
  transition: opacity .18s;
  pointer-events: none;
}
.toast.show { opacity: 1; }
@media (max-width: 1040px) {
  .app { grid-template-columns: 1fr; }
  .side { display: none; }
  .shell { padding: 24px 16px; }
  .metrics { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .top { align-items: flex-start; flex-direction: column; }
  .challenge { grid-template-columns: 1fr; }
  .language-grid, .donut-wrap { grid-template-columns: 1fr; }
  .row { grid-template-columns: 1fr; }
  .actions { opacity: 1; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">
      <span class="mark"><i></i><i></i><i></i><i></i></span>
      <span class="brand-name">Dictate</span>
      <span class="pill">EN/PT</span>
    </div>
    <nav class="nav">
      <button class="nav-item active" data-nav="home" onclick="navTo('home')"><span class="nav-ico">⌘</span>Home</button>
      <button class="nav-item" data-nav="language" onclick="navTo('language')"><span class="nav-ico">◌</span>Language</button>
      <button class="nav-item" data-nav="phrases" onclick="navTo('phrases')"><span class="nav-ico">✎</span>Phrase Bank</button>
      <button class="nav-item" data-nav="categories" onclick="navTo('categories')"><span class="nav-ico">◇</span>Categories</button>
    </nav>
    <div class="trial-card" onclick="navTo('challenge')" role="button" tabindex="0">
      <div class="trial-title">100 Words a Day</div>
      <div id="side-progress-text">0 of 100 words</div>
      <div class="mini-bar"><span id="side-progress"></span></div>
      <div style="color:var(--muted);font-size:13px">Speak messy English. Fix it after.</div>
    </div>
    <div class="side-foot">
      Ctrl+Space starts dictation. Use English first, Portuguese when blocked.
    </div>
  </aside>
  <main class="shell" id="scroll-root">
    <div class="top" id="home">
      <h1>Welcome back, Francisco</h1>
      <div class="top-stats">
        <span class="chip">🔥 <span id="s-streak">0</span> day streak</span>
        <span class="chip">🚀 <span id="s-week">0</span> words this week</span>
        <span class="chip">🏅 <span id="s-wpm">0</span> WPM</span>
      </div>
    </div>

    <section class="challenge" id="challenge">
      <div>
        <h2>100 Words a Day Challenge</h2>
        <p>Daily speaking reps across English and Portuguese.</p>
        <div class="progress"><span id="challenge-progress"></span></div>
        <div class="progress-label"><span id="challenge-label">0/100 WORDS</span></div>
      </div>
      <div class="logo-tile">▥</div>
    </section>

    <section class="metrics">
      <div class="panel pad" id="language">
        <h3 class="panel-title">Today's Language Mix</h3>
        <div class="language-grid">
          <div class="metric-card">
            <div class="metric-num" id="m-en">0%</div>
            <div class="metric-label">English words</div>
          </div>
          <div class="metric-card">
            <div class="metric-num" id="m-pt">0%</div>
            <div class="metric-label">Portuguese words</div>
          </div>
          <div class="metric-card">
            <div class="metric-num" id="m-today">0</div>
            <div class="metric-label">words today</div>
          </div>
        </div>
        <div class="split-bar">
          <span class="split-en" id="bar-en"></span>
          <span class="split-pt" id="bar-pt"></span>
          <span class="split-unknown" id="bar-unknown"></span>
        </div>
      </div>
      <div class="panel pad" id="categories">
        <h3 class="panel-title">Use Cases</h3>
        <div class="donut-wrap">
          <div class="donut" id="donut"></div>
          <div class="legend" id="legend"></div>
        </div>
      </div>
    </section>

    <section class="panel pad" id="phrases" style="margin-bottom:24px">
      <h3 class="panel-title">5 Phrases To Keep Today</h3>
      <div class="phrase-bank" id="phrase-bank"></div>
    </section>

    <div class="history-head">
      <h2>Today</h2>
      <button class="clear-btn" onclick="clearAll()">Clear history</button>
    </div>
    <div id="list"></div>
  </main>
</div>
<div class="toast" id="toast"></div>

<script>
let historyCache = [];
let editingTs = null;
const DEMO_MODE = new URLSearchParams(window.location.search).has('demo');
const DEMO_STATS = {
  total_words: 18420,
  total_seconds: 6420,
  transcripts: 248,
  wpm: 172,
  today: {
    words: 427,
    seconds: 154,
    transcripts: 12,
    wpm: 166,
    en_words: 294,
    pt_words: 119,
    unknown_words: 14,
    en_pct: 69,
    pt_pct: 28,
    unknown_pct: 3
  },
  week: {words: 6230, streak: 12},
  categories: [
    {key:'code', label:'Code', color:'#171717', words:6420, count:72, pct:35},
    {key:'content', label:'Content', color:'#7c3aed', words:5150, count:61, pct:28},
    {key:'business', label:'Business', color:'#0f766e', words:3290, count:43, pct:18},
    {key:'english', label:'English', color:'#ea580c', words:2210, count:38, pct:12},
    {key:'fitness', label:'Fitness', color:'#16a34a', words:1350, count:19, pct:7}
  ],
  phrase_bank: [
    'How can we keep the local dashboard open?',
    'The server goes down after I restart the computer.',
    'Please rewrite this message in natural English.',
    'Update the GitHub repo with the new dashboard.',
    'Show me the useful words I should remember.'
  ]
};
const DEMO_HISTORY = [
  {
    ts: 1003,
    iso: new Date().toISOString(),
    text: 'How can we keep this local dashboard always open after the computer starts?',
    words: 13,
    duration: 5.2,
    meta: {language:'en', en_pct:100, pt_pct:0, category_label:'Code'}
  },
  {
    ts: 1002,
    iso: new Date(Date.now() - 1000 * 60 * 24).toISOString(),
    text: 'Please update the GitHub repo with the new dashboard screenshot and setup instructions.',
    words: 12,
    duration: 4.7,
    meta: {language:'en', en_pct:100, pt_pct:0, category_label:'Code'}
  },
  {
    ts: 1001,
    iso: new Date(Date.now() - 1000 * 60 * 51).toISOString(),
    text: 'I want to speak in English first and use Portuguese only when I get stuck.',
    words: 15,
    duration: 6.1,
    meta: {language:'mixed', en_pct:87, pt_pct:13, category_label:'English'}
  }
];

function setActiveNav(name) {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.nav === name);
  });
}
function navTo(name) {
  const target = document.getElementById(name);
  if (!target) return;
  target.scrollIntoView({behavior: 'smooth', block: 'start'});
  const activeName = name === 'challenge' ? 'home' : name;
  setActiveNav(activeName);
}
function esc(s) {
  return String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
}
function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('pt-PT', {hour: '2-digit', minute: '2-digit'});
}
function fmtDay(iso) {
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'TODAY';
  if (d.toDateString() === y.toDateString()) return 'YESTERDAY';
  return d.toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long'}).toUpperCase();
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400);
}
async function copyText(txt) {
  await navigator.clipboard.writeText(txt);
  toast('Copied');
}
async function delEntry(ts) {
  if (DEMO_MODE) {
    toast('Demo mode');
    return;
  }
  await fetch('/api/history?ts=' + encodeURIComponent(ts), {method: 'DELETE'});
  await load();
}
async function clearAll() {
  if (DEMO_MODE) {
    toast('Demo mode');
    return;
  }
  if (!confirm('Delete all transcripts?')) return;
  await fetch('/api/history', {method: 'DELETE'});
  await load();
}
function editEntry(ts) {
  editingTs = ts;
  renderList(historyCache);
}
function cancelEdit() {
  editingTs = null;
  renderList(historyCache);
}
async function saveEdit(ts) {
  const el = document.getElementById('edit-' + ts);
  if (DEMO_MODE) {
    const item = historyCache.find(e => String(e.ts) === String(ts));
    if (item) item.text = el.value;
    editingTs = null;
    toast('Saved in demo');
    renderList(historyCache);
    return;
  }
  await fetch('/api/history?ts=' + encodeURIComponent(ts), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: el.value})
  });
  editingTs = null;
  toast('Saved');
  await load();
}
function languageLabel(meta) {
  if (!meta) return 'unknown';
  if (meta.language === 'en') return 'English';
  if (meta.language === 'pt') return 'Portuguese';
  if (meta.language === 'mixed') return 'Mixed EN/PT';
  return 'Unknown';
}
function renderDonut(categories) {
  const active = categories.filter(c => c.words > 0).slice(0, 6);
  const donut = document.getElementById('donut');
  const legend = document.getElementById('legend');
  if (!active.length) {
    donut.style.background = 'conic-gradient(#d6d3d1 0deg 360deg)';
    legend.innerHTML = '<div class="legend-row"><span class="legend-left"><span class="dot" style="background:#d6d3d1"></span>No data yet</span><b>0%</b></div>';
    return;
  }
  let start = 0;
  const parts = [];
  for (const c of active) {
    const deg = Math.max(2, c.pct * 3.6);
    parts.push(`${c.color} ${start}deg ${start + deg}deg`);
    start += deg;
  }
  if (start < 360) parts.push(`#e5e1d8 ${start}deg 360deg`);
  donut.style.background = `conic-gradient(${parts.join(',')})`;
  legend.innerHTML = active.map(c => `
    <div class="legend-row">
      <span class="legend-left"><span class="dot" style="background:${c.color}"></span>${esc(c.label)}</span>
      <b>${c.pct}%</b>
    </div>`).join('');
}
function renderPhrases(phrases) {
  document.getElementById('phrase-bank').innerHTML = phrases.map(p => `
    <div class="phrase">
      <span>${esc(p)}</span>
      <button onclick='copyText(${JSON.stringify(p)})'>Copy</button>
    </div>
  `).join('');
}
function renderList(hist) {
  const list = document.getElementById('list');
  if (!hist.length) {
    list.innerHTML = '<div class="empty">No transcripts yet.<br>Press <b>Ctrl+Space</b> to start dictating.</div>';
    return;
  }
  let html = '', lastDay = '';
  for (const e of hist) {
    const day = fmtDay(e.iso);
    if (day !== lastDay) {
      html += `<div class="day">${day}</div>`;
      lastDay = day;
    }
    const meta = e.meta || {};
    const isEditing = String(editingTs) === String(e.ts);
    const content = isEditing ? `
      <div class="editor">
        <textarea id="edit-${e.ts}">${esc(e.text)}</textarea>
        <div class="editor-actions">
          <button class="primary" onclick="saveEdit(${JSON.stringify(e.ts)})">Save</button>
          <button class="secondary" onclick="cancelEdit()">Cancel</button>
        </div>
      </div>` : `
      <div class="text">${esc(e.text)}</div>
      <div class="meta">
        <span class="tag">${languageLabel(meta)} · ${meta.en_pct || 0}% EN / ${meta.pt_pct || 0}% PT</span>
        <span class="tag">${esc(meta.category_label || 'General')}</span>
        <span class="tag">${e.words || 0} words</span>
      </div>`;
    html += `
      <div class="row">
        <div class="time">${fmtTime(e.iso)}</div>
        <div>${content}</div>
        <div class="actions">
          <button class="btn" onclick='copyText(${JSON.stringify(e.text)})' title="Copy">⎘</button>
          <button class="btn" onclick="editEntry(${JSON.stringify(e.ts)})" title="Edit">✎</button>
          <button class="btn danger" onclick="delEntry(${JSON.stringify(e.ts)})" title="Delete">×</button>
        </div>
      </div>`;
  }
  list.innerHTML = html;
}
async function load() {
  const [hist, stats] = DEMO_MODE
    ? [DEMO_HISTORY, DEMO_STATS]
    : await Promise.all([
      fetch('/api/history').then(r => r.json()),
      fetch('/api/stats').then(r => r.json()),
    ]);
  historyCache = hist;
  const today = stats.today || {};
  const challenge = Math.min(100, today.words || 0);
  document.getElementById('s-streak').textContent = stats.week?.streak || 0;
  document.getElementById('s-week').textContent = (stats.week?.words || 0).toLocaleString('pt-PT');
  document.getElementById('s-wpm').textContent = today.wpm || stats.wpm || 0;
  document.getElementById('m-en').textContent = `${today.en_pct || 0}%`;
  document.getElementById('m-pt').textContent = `${today.pt_pct || 0}%`;
  document.getElementById('m-today').textContent = (today.words || 0).toLocaleString('pt-PT');
  document.getElementById('challenge-progress').style.width = `${challenge}%`;
  document.getElementById('side-progress').style.width = `${challenge}%`;
  document.getElementById('challenge-label').textContent = `${today.words || 0}/100 WORDS`;
  document.getElementById('side-progress-text').textContent = `${today.words || 0} of 100 words`;
  document.getElementById('bar-en').style.width = `${today.en_pct || 0}%`;
  document.getElementById('bar-pt').style.width = `${today.pt_pct || 0}%`;
  document.getElementById('bar-unknown').style.width = `${today.unknown_pct || 0}%`;
  renderDonut(stats.categories || []);
  renderPhrases(stats.phrase_bank || []);
  renderList(hist);
}
load();
setInterval(load, 5000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    start(Path.home() / "dictate" / "history.jsonl")
    print("dashboard at http://localhost:7717")
    while True:
        time.sleep(3600)
