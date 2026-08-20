"""HTTP wrapper around whisper_trt, run *inside* the dustynv/whisper_trt image.

Two reasons this is a separate long-lived service rather than a library call:

1. ``whisper_trt`` aborts with ``double free or corruption`` during interpreter
   teardown. Inference is fine; only shutdown is unsafe. A process that stays
   up never reaches that path, and a crash cannot take the agent down with it.
2. Building the TensorRT engine costs 150 s (base.en) to 280 s (small.en). It
   is cached, but the model must stay resident to hold per-turn latency at the
   measured ~0.35 s.

Deliberately stdlib-only: the image ships neither fastapi nor uvicorn, and
adding them would mean maintaining a derived image for one POST route. ASR is
serialised on the GPU regardless, so a threaded stdlib server costs nothing.

Run it with::

    docker run -d --name andy-asr --runtime nvidia -p 8881:8881 \
      -v <repo>/andy-server/services:/svc \
      -v /opt/andy/whisper_cache:/root/.cache \
      --entrypoint python3 dustynv/whisper_trt:r36.3.0 /svc/whisper_service.py
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

MODEL_NAME = os.environ.get("ANDY_ASR_MODEL", "base.en")
PORT = int(os.environ.get("ANDY_ASR_PORT", "8881"))
SAMPLE_RATE = 16000

_model = None
_load_seconds = 0.0
_gpu_lock = threading.Lock()  # one transcription at a time on the GPU


def _load_model() -> None:
    global _model, _load_seconds
    from whisper_trt import load_trt_model

    t0 = time.time()
    _model = load_trt_model(MODEL_NAME)
    _load_seconds = time.time() - t0
    print(f"[andy-asr] {MODEL_NAME} ready in {_load_seconds:.1f}s", flush=True)


def _to_pcm16(raw: bytes) -> bytes:
    """Accept a WAV container or bare PCM16; always return mono 16 kHz PCM16."""
    if raw[:4] != b"RIFF":
        return raw
    with wave.open(io.BytesIO(raw)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit")
        pcm = w.readframes(w.getnframes())
        if w.getnchannels() == 2:
            a = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).mean(axis=1)
            pcm = a.astype("<i2").tobytes()
        if w.getframerate() != SAMPLE_RATE:
            a = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            n = int(round(a.size * SAMPLE_RATE / w.getframerate()))
            a = np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a)
            pcm = np.clip(a, -32768, 32767).astype("<i2").tobytes()
        return pcm


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        pass

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            self._send(200, {"ok": _model is not None, "model": MODEL_NAME,
                             "load_seconds": round(_load_seconds, 1)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.path.startswith("/transcribe"):
            self._send(404, {"error": "not found"})
            return
        if _model is None:
            self._send(503, {"error": "model not loaded"})
            return

        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            self._send(400, {"error": "empty body"})
            return

        try:
            pcm = _to_pcm16(raw)
        except Exception as exc:
            self._send(400, {"error": f"bad audio: {exc}"})
            return

        seconds = len(pcm) / 2 / SAMPLE_RATE
        if seconds < 0.1:
            self._send(200, {"text": "", "seconds": round(seconds, 3), "rtf": 0.0})
            return

        # whisper_trt transcribes from a path; tmpfs keeps it off the SSD.
        path = f"/dev/shm/andy_asr_{threading.get_ident()}.wav"
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)

        try:
            t0 = time.time()
            with _gpu_lock:
                result = _model.transcribe(path)
            dt = time.time() - t0
        except Exception as exc:
            self._send(500, {"error": f"transcribe failed: {exc}"})
            return
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        text = (result.get("text") if isinstance(result, dict) else str(result)).strip()
        self._send(200, {"text": text, "seconds": round(seconds, 2),
                         "proc": round(dt, 3), "rtf": round(dt / seconds, 3)})


if __name__ == "__main__":
    _load_model()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[andy-asr] listening on :{PORT}", flush=True)
    srv.serve_forever()
