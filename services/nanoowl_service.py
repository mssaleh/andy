"""HTTP wrapper around NanoOWL, run *inside* the dustynv/nanoowl image.

Andy already has a way of looking: a frame goes to a vision-language model and
comes back as a sentence. That answers "what can you see?" and nothing else
well. "Is anyone here?", "are my keys on the desk?" and "is the mug still
there?" are questions about named things, and a sentence is a poor way to ask
them -- it costs a round trip to a large model and returns prose that has to be
believed rather than a score that can be thresholded.

NanoOWL answers those directly and locally. It is open-vocabulary, so the names
are not a fixed class list, and it is compiled to TensorRT, so the answer costs
milliseconds rather than a conversation with a remote model.

Like the recogniser's wrapper this is a separate long-lived process, for the
same two reasons:

1. Building the TensorRT image encoder engine is expensive and happens once.
   A process that stays up pays it once; a process per query pays it always.
2. The model must stay resident. Loading OWL-ViT per question would make a
   question about the room slower than asking a person to look.

Deliberately stdlib-only: the image ships neither fastapi nor uvicorn, and
adding them would mean maintaining a derived image for two routes. Detection is
serialised on the GPU regardless, so a threaded stdlib server costs nothing.

The image already carries a built TensorRT image encoder at
`/opt/nanoowl/data/owl_image_encoder_patch32.engine`, so there is nothing to
build and nothing to mount for it; the model is resident 3.5 s after start.

Run it with::

    docker run -d --name andy-sight --runtime nvidia --restart unless-stopped \
      -p 8883:8883 -v <repo>/services:/svc:ro \
      --entrypoint python3 dustynv/nanoowl:r36.4.0 /svc/nanoowl_service.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.environ.get("ANDY_OWL_MODEL", "google/owlvit-base-patch32")
ENGINE = os.environ.get(
    "ANDY_OWL_ENGINE", "/opt/nanoowl/data/owl_image_encoder_patch32.engine"
)
PORT = int(os.environ.get("ANDY_OWL_PORT", "8883"))
#: Measured on a real desk frame rather than chosen. At 0.15 one monitor comes
#: back six times and cables appear that are not there; at 0.35 the monitor
#: that is there disappears. Between 0.25 and 0.30 the answer is exactly the
#: objects in the room, which is the only band worth speaking aloud.
THRESHOLD = float(os.environ.get("ANDY_OWL_THRESHOLD", "0.25"))
MAX_IMAGE_BYTES = 4 * 1024 * 1024

_predictor = None
_load_seconds = 0.0
_gpu_lock = threading.Lock()
#: Encoding a phrase is a transformer pass, and Andy asks the same handful of
#: questions repeatedly -- "a person" above all. Keyed by the exact phrase
#: tuple, because the predictor wants encodings for the whole set at once.
_text_cache: dict[tuple[str, ...], object] = {}
_CACHE_LIMIT = 64


def _load_model() -> None:
    global _predictor, _load_seconds
    from nanoowl.owl_predictor import OwlPredictor

    start = time.time()
    _predictor = OwlPredictor(MODEL, image_encoder_engine=ENGINE)
    _load_seconds = time.time() - start
    print(f"[andy-sight] {MODEL} ready in {_load_seconds:.1f}s", flush=True)


def _encodings(phrases: tuple[str, ...]):
    cached = _text_cache.get(phrases)
    if cached is not None:
        return cached
    encoded = _predictor.encode_text(list(phrases))
    if len(_text_cache) >= _CACHE_LIMIT:
        _text_cache.clear()
    _text_cache[phrases] = encoded
    return encoded


def _overlap(a: list, b: list) -> float:
    """Intersection over union of two boxes, for suppressing repeats."""
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _suppress(entries: list[dict], iou: float = 0.45) -> list[dict]:
    """One entry per real thing.

    The predictor returns every box that cleared the threshold, so a single
    monitor comes back six times. Spoken aloud that is not a description of a
    room, it is a fault. Boxes are kept best-first and a later box naming the
    same thing in the same place is dropped.
    """
    kept: list[dict] = []
    for entry in sorted(entries, key=lambda e: e["confidence"], reverse=True):
        if any(
            other["thing"] == entry["thing"]
            and _overlap(entry["box"], other["box"]) > iou
            for other in kept
        ):
            continue
        kept.append(entry)
    return kept


def _detect(image_bytes: bytes, phrases: tuple[str, ...], threshold: float):
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    with _gpu_lock:
        output = _predictor.predict(
            image=image,
            text=list(phrases),
            text_encodings=_encodings(phrases),
            threshold=threshold,
            pad_square=False,
        )
    found = []
    boxes = getattr(output, "boxes", None)
    labels = getattr(output, "labels", None)
    scores = getattr(output, "scores", None)
    count = 0 if labels is None else len(labels)
    for index in range(count):
        label = int(labels[index])
        score = float(scores[index])
        box = [float(value) for value in boxes[index]]
        centre_x = (box[0] + box[2]) / 2.0
        found.append(
            {
                "thing": phrases[label] if label < len(phrases) else "?",
                "confidence": round(score, 3),
                # Where it is, in words the server can use without knowing the
                # frame size: a bearing rather than a pixel.
                "side": (
                    "left" if centre_x < width / 3
                    else "right" if centre_x > 2 * width / 3
                    else "ahead"
                ),
                "box": [round(value, 1) for value in box],
            }
        )
    return _suppress(found), width, height


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
            self._send(
                200,
                {
                    "ok": _predictor is not None,
                    "model": MODEL,
                    "load_seconds": round(_load_seconds, 1),
                    "cached_phrase_sets": len(_text_cache),
                },
            )
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.path.startswith("/detect"):
            self._send(404, {"error": "not found"})
            return
        if _predictor is None:
            self._send(503, {"error": "model not loaded"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send(400, {"error": "empty body"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            image_bytes = base64.b64decode(payload["image_base64"])
            phrases = tuple(
                str(phrase).strip()
                for phrase in payload["phrases"]
                if str(phrase).strip()
            )
            threshold = float(payload.get("threshold", THRESHOLD))
        except Exception as exc:
            self._send(400, {"error": f"bad request: {exc}"})
            return
        if not phrases:
            self._send(400, {"error": "no phrases to look for"})
            return
        if len(image_bytes) > MAX_IMAGE_BYTES:
            self._send(413, {"error": "image too large"})
            return

        try:
            start = time.time()
            found, width, height = _detect(image_bytes, phrases, threshold)
            elapsed = time.time() - start
        except Exception as exc:
            self._send(500, {"error": f"detection failed: {exc}"})
            return

        self._send(
            200,
            {
                "found": found,
                "looked_for": list(phrases),
                "frame": {"width": width, "height": height},
                "proc": round(elapsed, 3),
            },
        )


if __name__ == "__main__":
    _load_model()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[andy-sight] listening on :{PORT}", flush=True)
    server.serve_forever()
