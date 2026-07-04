#!/usr/bin/env python3
"""
Dictate daemon — Wispr Flow clone, 100% local.

Long-running process: loads MLX Whisper once (pre-warm) and listens on a
Unix socket for commands from the Hammerspoon hotkey layer.

Commands (one line, newline-terminated):
    START       begin capturing mic audio
    STOP        stop capture, transcribe, copy text to clipboard
    STOP_PASTE  stop capture, transcribe, copy + paste
    PASTE       simulate Cmd+V into the frontmost app
    CANCEL      stop capture, discard audio
    PING        health check
    STATE       REC or IDLE
    LAST        last transcribed text
    BUSY        YES/NO — transcription in progress?
    RESULT      last transcription result as JSON
"""
import os
import sys
import json
import socket
import signal
import threading
import subprocess
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import mlx_whisper

from dashboard import start as start_dashboard

SOCK_PATH = "/tmp/dictate.sock"
LOG_PATH = Path.home() / "dictate" / "logs" / "daemon.log"
HISTORY_PATH = Path.home() / "dictate" / "history.jsonl"
MODEL = "mlx-community/whisper-large-v3-turbo"
SAMPLE_RATE = 16000
LANG = None  # auto-detect: supports Portuguese, English, and mixed dictation better than forcing PT
DASHBOARD_PORT = 7717
MIN_SPEECH_RMS = 0.002
CLIENT_RECV_TIMEOUT = 2.0
MAX_RECORDING_SECONDS = 300
MAX_AUDIO_STALL_SECONDS = 20

_transcribe_lock = threading.Lock()
_transcribe_busy = False
_cancel_event = threading.Event()


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    # stdout goes to launchd's StandardOutPath; if the disk is full a flush
    # raises ENOSPC. That MUST NOT kill the calling thread (it used to wedge
    # the accept loop / transcription thread), so swallow every write error.
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass


def write_status(status: str) -> None:
    try:
        with open("/tmp/dictate.status", "w") as f:
            f.write(status)
    except Exception:
        pass


def write_level(level: float) -> None:
    try:
        with open("/tmp/dictate.level", "w") as f:
            f.write(f"{level:.4f}")
    except Exception:
        pass


def write_result(text: str) -> None:
    try:
        with open("/tmp/dictate.result", "w") as f:
            json.dump({"text": text, "ts": time.time()}, f, ensure_ascii=False)
    except Exception:
        pass


def select_input_device() -> int | None:
    try:
        devices = sd.query_devices()
    except Exception as e:
        log(f"audio device query error: {e}")
        return None

    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and "MacBook" in d["name"]:
            return i

    available = [
        f"{i}:{d['name']}"
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]
    raise RuntimeError(
        "MacBook microphone not found; refusing to use another input. "
        f"Available inputs: {available}"
    )


def input_device_name(device: int | None) -> str:
    if device is None:
        return "system-default"
    try:
        return str(sd.query_devices()[device]["name"])
    except Exception:
        return "unknown"


class Recorder:
    def __init__(self) -> None:
        self.stream: sd.InputStream | None = None
        self.frames: list[np.ndarray] = []
        self.lock = threading.Lock()
        self.started_at: float | None = None
        self.last_frame_at: float | None = None
        self.generation = 0

    def _cb(self, indata, frames, t, status) -> None:
        if status:
            log(f"audio status: {status}")
        with self.lock:
            self.frames.append(indata.copy())
            self.last_frame_at = time.time()
        try:
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            write_level(rms)
        except Exception:
            pass

    def _watchdog(self, generation: int) -> None:
        try:
            while True:
                time.sleep(5)
                with self.lock:
                    if self.stream is None or self.generation != generation:
                        return
                    started_at = self.started_at
                    last_frame_at = self.last_frame_at
                if started_at is None:
                    return

                now = time.time()
                elapsed = now - started_at
                stalled_for = now - last_frame_at if last_frame_at else elapsed
                if elapsed >= MAX_RECORDING_SECONDS:
                    log(f"recording watchdog cancelling stale recording ({elapsed:.1f}s)")
                    self.stop(discard=True)
                    write_status("ready")
                    write_level(0.0)
                    return
                if stalled_for >= MAX_AUDIO_STALL_SECONDS:
                    log(f"recording watchdog cancelling stalled audio stream ({stalled_for:.1f}s without frames)")
                    self.stop(discard=True)
                    write_status("ready")
                    write_level(0.0)
                    return
        except Exception as e:
            log(f"recording watchdog error: {e}")
            try:
                self.stop(discard=True)
            except Exception:
                pass
            write_status("ready")
            write_level(0.0)

    def _close_stream(self, stream: sd.InputStream) -> None:
        # PortAudio/CoreAudio can deadlock in Pa_StopStream on macOS. Abort does
        # not wait for pending buffers and still lets us use the frames already
        # collected by the callback.
        try:
            stream.abort()
        except Exception as e:
            log(f"stream abort error: {e}")
        try:
            stream.close()
        except Exception as e:
            log(f"stream close error: {e}")

    def start(self) -> None:
        if self.stream is not None:
            log("already recording — aborting old stream")
            old_stream = self.stream
            self.stream = None
            self._close_stream(old_stream)
        with self.lock:
            self.frames = []
            self.started_at = None
            self.last_frame_at = None
            self.generation += 1
        device = select_input_device()
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._cb,
            blocksize=1024,
            device=device,
        )
        self.stream.start()
        with self.lock:
            self.started_at = time.time()
            self.last_frame_at = self.started_at
            generation = self.generation
        write_status("recording")
        log(f"REC start (device={device}, name={input_device_name(device)})")
        threading.Thread(target=self._watchdog, args=(generation,), daemon=True).start()

    def stop(self, discard: bool = False) -> np.ndarray:
        if self.stream is None:
            return np.zeros(0, dtype=np.float32)
        stream = self.stream
        self.stream = None
        write_level(0.0)
        self._close_stream(stream)
        with self.lock:
            self.started_at = None
            self.last_frame_at = None
            self.generation += 1
            if not self.frames:
                if discard:
                    self.frames = []
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self.frames, axis=0).flatten()
            if discard:
                self.frames = []
        log(f"REC stop ({len(audio)/SAMPLE_RATE:.2f}s)")
        if discard:
            return np.zeros(0, dtype=np.float32)
        return audio


def save_history(text: str, duration: float) -> None:
    if not text.strip():
        return
    try:
        from dashboard import analyze_text

        meta = analyze_text(text)
    except Exception:
        meta = {}
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": text,
        "words": len(text.split()),
        "duration": round(duration, 2),
        "meta": meta,
    }
    try:
        with open(HISTORY_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"history save error: {e}")


def audio_rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def transcribe_direct(audio: np.ndarray) -> str:
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL,
        language=LANG,
        fp16=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.95,
        logprob_threshold=-2.0,
        compression_ratio_threshold=4.0,
        temperature=0.0,
    )
    return (result.get("text") or "").strip()


def transcribe(audio: np.ndarray) -> str:
    if audio.size < SAMPLE_RATE * 0.15:
        return ""
    rms = audio_rms(audio)
    if rms < MIN_SPEECH_RMS:
        log(f"audio skipped as silence (rms={rms:.5f})")
        return ""
    duration = audio.size / SAMPLE_RATE
    log(f"transcribing {duration:.1f}s of audio...")
    write_status("transcribing")
    t0 = time.time()
    txt = transcribe_direct(audio)
    elapsed = time.time() - t0
    log(f"transcribed in {elapsed:.2f}s: {txt!r}")
    write_status("ready")
    save_history(txt, duration)
    return txt


def copy_to_clipboard(text: str) -> None:
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(text.encode("utf-8"))


def paste() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
        check=False,
    )


def safe_send(conn: socket.socket, data: bytes) -> None:
    try:
        conn.sendall(data)
    except (BrokenPipeError, ConnectionResetError):
        log("client disconnected before response")


def handle_stop(audio: np.ndarray, do_paste: bool, last_text_holder: list) -> None:
    global _transcribe_busy
    txt = ""
    try:
        with _transcribe_lock:
            txt = transcribe(audio)
        if _cancel_event.is_set():
            _cancel_event.clear()
            log("transcription cancelled, discarding result")
            write_result("")
            return

        if txt:
            last_text_holder[0] = txt
            copy_to_clipboard(txt)
            if do_paste:
                paste()
        write_result(txt)
    except Exception as e:
        log(f"stop/transcribe error: {e}")
        write_result("")
    finally:
        write_status("ready")
        _transcribe_busy = False


def warmup() -> None:
    write_status("warming")
    write_level(0.0)
    log("warming model...")
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    try:
        mlx_whisper.transcribe(silence, path_or_hf_repo=MODEL, language=LANG, fp16=True)
        log("model warm")
    except Exception as e:
        log(f"warmup error: {e}")
    write_status("ready")


def keep_warm() -> None:
    while True:
        time.sleep(300)
        try:
            silence = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
            t0 = time.time()
            mlx_whisper.transcribe(silence, path_or_hf_repo=MODEL, language=LANG, fp16=True)
            elapsed = time.time() - t0
            if elapsed > 5:
                log(f"keep-warm took {elapsed:.1f}s (memory pressure?)")
        except Exception as e:
            log(f"keep-warm error: {e}")


def serve() -> None:
    global _transcribe_busy
    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o600)
    srv.listen(16)
    log(f"listening on {SOCK_PATH}")

    rec = Recorder()
    last_text = [""]

    def shutdown(*_):
        log("shutdown")
        try:
            srv.close()
        finally:
            if os.path.exists(SOCK_PATH):
                os.unlink(SOCK_PATH)
            sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        with conn:
            conn.settimeout(CLIENT_RECV_TIMEOUT)
            try:
                data = conn.recv(64).decode("utf-8", "ignore").strip().upper()
            except socket.timeout:
                log("client connected without command; closing")
                continue
            except Exception:
                continue
            if not data:
                log("client sent empty command; closing")
                continue
            # A failing handler (e.g. mic gone -> rec.start raises, or a disk
            # error) must never escape the accept loop. If it does, the daemon
            # stops accepting commands while the process stays alive => the HUD
            # shows "recording" forever and no audio is captured. Contain it.
            try:
                if data == "START":
                    _cancel_event.clear()
                    rec.start()
                    safe_send(conn, b"OK\n")
                elif data in ("STOP", "STOP_PASTE"):
                    audio = rec.stop()
                    if _transcribe_busy:
                        log("transcription already in progress, skipping")
                        safe_send(conn, b'{"text":""}\n')
                        continue
                    do_paste = data == "STOP_PASTE"
                    _transcribe_busy = True
                    write_result("")
                    t = threading.Thread(
                        target=handle_stop,
                        args=(audio, do_paste, last_text),
                        daemon=True,
                    )
                    t.start()
                    safe_send(conn, b"TRANSCRIBING\n")
                elif data == "PASTE":
                    paste()
                    safe_send(conn, b"OK\n")
                elif data == "CANCEL":
                    rec.stop()
                    if _transcribe_busy:
                        _cancel_event.set()
                    else:
                        _cancel_event.clear()
                        write_result("")
                        write_status("ready")
                    log("CANCEL")
                    safe_send(conn, b"OK\n")
                elif data == "STATE":
                    if rec.stream is not None:
                        safe_send(conn, b"REC\n")
                    elif _transcribe_busy:
                        safe_send(conn, b"TRANSCRIBING\n")
                    else:
                        safe_send(conn, b"IDLE\n")
                elif data == "PING":
                    safe_send(conn, b"PONG\n")
                elif data == "LAST":
                    safe_send(conn, (last_text[0] + "\n").encode())
                elif data == "BUSY":
                    safe_send(conn, b"YES\n" if _transcribe_busy else b"NO\n")
                elif data == "RESULT":
                    try:
                        with open("/tmp/dictate.result") as f:
                            result = f.read()
                        safe_send(conn, result.encode() + b"\n")
                    except FileNotFoundError:
                        safe_send(conn, b'{"text":""}\n')
                else:
                    safe_send(conn, b"ERR\n")
            except Exception as e:
                log(f"command {data!r} failed: {e}")
                # never leave the daemon stuck in a phantom recording state
                try:
                    rec.stop(discard=True)
                except Exception:
                    pass
                _transcribe_busy = False
                write_status("ready")
                write_level(0.0)
                safe_send(conn, b"ERR\n")


if __name__ == "__main__":
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    start_dashboard(HISTORY_PATH, DASHBOARD_PORT)
    log(f"dashboard at http://localhost:{DASHBOARD_PORT}")
    warmup()
    threading.Thread(target=keep_warm, daemon=True).start()
    serve()
