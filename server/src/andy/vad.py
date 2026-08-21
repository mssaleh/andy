from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from math import exp, isqrt, log
from pathlib import Path
import sys
from typing import Protocol, runtime_checkable


class VADDecision(StrEnum):
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"
    NO_SPEECH_TIMEOUT = "no_speech_timeout"
    MAX_DURATION = "max_duration"


class FrameClassifier(Protocol):
    def __call__(self, frame: bytes) -> bool: ...


@runtime_checkable
class SpeechAware(Protocol):
    """A classifier that behaves differently once an utterance is running.

    Both detectors here want to know: the energy gate freezes its estimate of
    the room so an utterance cannot raise the bar behind itself, and the neural
    detector drops to a lower threshold so an ordinary dip between words does
    not read as the end of a sentence. A plain callable classifier is still a
    valid `FrameClassifier`; it simply is not told.
    """

    def set_speech_active(self, active: bool) -> None: ...


def frame_rms(frame: bytes) -> int:
    samples = array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0
    return isqrt(sum(sample * sample for sample in samples) // len(samples))


@dataclass(frozen=True, slots=True)
class EnergyConfig:
    """How far above its own room speech has to stand to count.

    The threshold is expressed as a contract rather than a level: only the
    loudest `1 - noise_quantile` of ambient frames may reach it, with
    `noise_ratio` of headroom on top. That contract holds in a library and in
    a workshop without either being measured in advance.
    """

    noise_quantile: float = 0.9
    noise_ratio: float = 1.2
    # A backstop for digital silence, not the operative threshold. Any real
    # room drives the level above this, and the ratio governs from there.
    min_speech_rms: int = 60
    noise_initial: int = 250
    noise_min: int = 40
    adapt_rate: float = 0.002

    def __post_init__(self) -> None:
        if self.min_speech_rms < 0 or self.noise_min < 0:
            raise ValueError("energy thresholds cannot be negative")
        if not 0.0 < self.noise_quantile < 1.0:
            raise ValueError("noise_quantile must be within (0, 1)")
        if self.noise_ratio < 1.0:
            raise ValueError("noise_ratio must be at least 1.0")
        if self.noise_initial < self.noise_min:
            raise ValueError("noise_initial cannot be below noise_min")
        if not 0.0 < self.adapt_rate <= 1.0:
            raise ValueError("adapt_rate must be within (0, 1]")


class EnergyGate:
    """Decide whether a frame stands above the room it was recorded in.

    WebRTC's detector judges voicing, not loudness. Broadband transients -- a
    keystroke, a click, a chair -- have speech-like spectra, so it reports them
    as speech however quiet they are, and a room's own noise is enough to hold
    a segment open indefinitely. Loudness relative to the room is the axis that
    separates a person talking from the room being a room.

    What the room "is" cannot be a constant, and it cannot be its quietest
    moment either: between two keystrokes a busy room falls to near silence,
    so a minimum describes the gaps rather than the noise. This tracks a high
    quantile of ambient frames instead -- the level only the loudest tenth of
    them reach -- and puts the threshold just above it. The estimate is frozen
    while speech is in progress so an utterance cannot raise the bar behind
    itself.
    """

    def __init__(self, config: EnergyConfig | None = None) -> None:
        self.config = config or EnergyConfig()
        self._speech_active = False
        self.reset()

    def reset(self) -> None:
        self._log_noise = log(float(self.config.noise_initial))
        self._speech_active = False
        self.begin_window()

    def begin_window(self) -> None:
        """Start per-capture accounting. The learned room level survives."""
        self.frames = 0
        self.admitted = 0
        self.peak_rms = 0
        self._window_rms: list[int] = []

    def set_speech_active(self, active: bool) -> None:
        self._speech_active = active

    @property
    def noise_level(self) -> int:
        return int(exp(self._log_noise))

    @property
    def threshold(self) -> int:
        return max(
            self.config.min_speech_rms,
            int(exp(self._log_noise) * self.config.noise_ratio),
        )

    def _track(self, rms: int) -> None:
        """Move the estimate toward the configured quantile of ambient frames.

        Stochastic quantile tracking: stepping up by `q` on frames above the
        estimate and down by `1 - q` on frames below it settles where the
        fraction above is `1 - q`. The walk is taken on the logarithm, which
        makes a step a fixed proportion rather than a fixed number of counts --
        the same rate then works at any room level, and a loud tail cannot
        bias the estimate upward the way it does when steps grow with it.
        """
        quantile = self.config.noise_quantile
        observed = log(float(max(rms, 1)))
        if observed > self._log_noise:
            self._log_noise += self.config.adapt_rate * quantile
        else:
            self._log_noise -= self.config.adapt_rate * (1.0 - quantile)
        self._log_noise = max(
            log(float(self.config.noise_min)), self._log_noise
        )

    def observe(self, rms: int) -> None:
        """Record a frame's level without letting it decide anything."""
        self.frames += 1
        self.peak_rms = max(self.peak_rms, rms)
        self._window_rms.append(rms)
        if not self._speech_active:
            self._track(rms)

    def admits(self, rms: int) -> bool:
        self.observe(rms)
        if rms >= self.threshold:
            self.admitted += 1
            return True
        return False

    def percentile(self, fraction: float) -> int:
        if not self._window_rms:
            return 0
        ordered = sorted(self._window_rms)
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return ordered[index]

    def levels(self) -> str:
        """The room this capture happened in, with nothing about the verdict."""
        return (
            f"noise={self.noise_level} "
            f"rms_p50={self.percentile(0.50)} rms_p90={self.percentile(0.90)} "
            f"rms_p99={self.percentile(0.99)} peak_rms={self.peak_rms}"
        )

    def summary(self) -> str:
        """What this capture measured, so a threshold can be read off a room."""
        return (
            f"noise={self.noise_level} threshold={self.threshold} "
            f"rms_p50={self.percentile(0.50)} rms_p90={self.percentile(0.90)} "
            f"rms_p99={self.percentile(0.99)} peak_rms={self.peak_rms} "
            f"admitted={self.admitted}/{self.frames}"
        )


class WebRtcClassifier:
    def __init__(self, *, sample_rate: int, mode: int) -> None:
        import webrtcvad

        self._sample_rate = sample_rate
        self._vad = webrtcvad.Vad(mode)

    def __call__(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, self._sample_rate)


#: Silero's published wrapper is the authority on how the model is driven, and
#: none of this is inferable from the ONNX signature. The model takes exactly
#: 512 samples at 16 kHz, preceded by the previous chunk's last 64 samples, so
#: the tensor handed to it is 576 wide. Feeding it 512 samples with no context
#: runs without error and reports speech as near-silence.
SILERO_CHUNK_SAMPLES = 512
SILERO_CONTEXT_SAMPLES = 64
SILERO_STATE_SHAPE = (2, 1, 128)

DEFAULT_MODEL_PATH = Path(__file__).with_name("models") / "silero_vad.onnx"


@dataclass(frozen=True, slots=True)
class SileroConfig:
    """Where a frame stops being the room and starts being a person.

    Two thresholds rather than one. Speech has to clear the higher bar to
    begin, and then only the lower one to continue, because the probability
    dips between words and inside stopped consonants. One threshold either
    starts on a cough or chops a sentence into pieces.
    """

    speech_threshold: float = 0.5
    keep_threshold: float = 0.35
    model_path: Path = DEFAULT_MODEL_PATH

    def __post_init__(self) -> None:
        if not 0.0 < self.speech_threshold < 1.0:
            raise ValueError("speech_threshold must be within (0, 1)")
        if not 0.0 < self.keep_threshold <= self.speech_threshold:
            raise ValueError(
                "keep_threshold must be within (0, speech_threshold]"
            )


class SileroModel:
    """The loaded network, shared by every capture in the session.

    Held apart from the classifier because a detector is built per capture
    window and the session costs far more than a window does. Loading it once
    at startup also means a missing or unreadable model is a server that does
    not start, rather than a robot that has gone quietly deaf.
    """

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        import numpy
        import onnxruntime

        self._numpy = numpy
        path = Path(model_path)
        if not path.is_file():
            raise RuntimeError(f"Silero VAD model is missing: {path}")
        options = onnxruntime.SessionOptions()
        # One frame at a time on an otherwise busy machine: a thread pool costs
        # more in handoff than the 0.06 ms of arithmetic it would parallelise.
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self._session = onnxruntime.InferenceSession(
            str(path),
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        self.path = path

    def initial_state(self):
        return self._numpy.zeros(SILERO_STATE_SHAPE, dtype=self._numpy.float32)

    def initial_context(self):
        return self._numpy.zeros(
            (1, SILERO_CONTEXT_SAMPLES), dtype=self._numpy.float32
        )

    def probability(self, chunk, state, context) -> tuple[float, object, object]:
        """One 512-sample chunk in, one speech probability and new state out."""
        numpy = self._numpy
        padded = numpy.concatenate([context, chunk], axis=1)
        output, next_state = self._session.run(
            None,
            {
                "input": padded,
                "state": state,
                "sr": numpy.array(16_000, dtype=numpy.int64),
            },
        )
        return (
            float(output[0][0]),
            next_state,
            padded[:, -SILERO_CONTEXT_SAMPLES:],
        )


class SileroClassifier:
    """Judge speech with a network instead of with a spectrum heuristic.

    WebRTC's detector judges voicing. A keystroke, a chair, a fan and mains
    hum all have speech-like spectra, so it reports them as speech at any
    volume, and loudness cannot rescue it: measured on this rig, 60 Hz hum at
    RMS 2895 is louder than real speech at RMS 1639, and WebRTC calls it
    speech in 99.6% of frames against 0% for this model. No energy threshold
    separates those two, because the noise is the louder of them.

    The detector upstream works on a 20 ms frame grid and this model insists on
    32 ms chunks, so frames are accumulated and a frame carries the most recent
    verdict. That verdict is at most one chunk behind the audio, which is
    nothing against 60 ms of evidence to start and 800 ms of silence to end.
    """

    def __init__(
        self, model: SileroModel, config: SileroConfig | None = None
    ) -> None:
        self._model = model
        self.config = config or SileroConfig()
        self._numpy = model._numpy
        self._speech_active = False
        self.reset()

    def reset(self) -> None:
        self._state = self._model.initial_state()
        self._context = self._model.initial_context()
        self._samples = self._numpy.zeros(0, dtype=self._numpy.float32)
        self._speech_active = False
        self._last_speech = False
        self.chunks = 0
        self.voiced_chunks = 0
        self._probabilities: list[float] = []

    def set_speech_active(self, active: bool) -> None:
        self._speech_active = active

    @property
    def threshold(self) -> float:
        config = self.config
        return (
            config.keep_threshold if self._speech_active
            else config.speech_threshold
        )

    def __call__(self, frame: bytes) -> bool:
        numpy = self._numpy
        samples = (
            numpy.frombuffer(
                frame[: len(frame) - (len(frame) % 2)], dtype="<i2"
            ).astype(numpy.float32)
            / 32_768.0
        )
        self._samples = numpy.concatenate([self._samples, samples])
        while len(self._samples) >= SILERO_CHUNK_SAMPLES:
            chunk = self._samples[:SILERO_CHUNK_SAMPLES].reshape(1, -1)
            self._samples = self._samples[SILERO_CHUNK_SAMPLES:]
            probability, self._state, self._context = self._model.probability(
                chunk, self._state, self._context
            )
            self._probabilities.append(probability)
            self.chunks += 1
            self._last_speech = probability >= self.threshold
            if self._last_speech:
                self.voiced_chunks += 1
        return self._last_speech

    def percentile(self, fraction: float) -> float:
        if not self._probabilities:
            return 0.0
        ordered = sorted(self._probabilities)
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return ordered[index]

    def summary(self) -> str:
        peak = max(self._probabilities, default=0.0)
        return (
            f"vad=silero speech_p50={self.percentile(0.50):.2f} "
            f"speech_p90={self.percentile(0.90):.2f} peak_speech={peak:.2f} "
            f"voiced={self.voiced_chunks}/{self.chunks}"
        )


class MeasuredClassifier:
    """Let the detector decide, and measure the room it decided in.

    The energy gate exists to compensate for a classifier that cannot tell a
    fan from a person. A classifier that can makes the gate's veto strictly
    harmful: an AND on loudness can only discard frames the detector already
    accepted, and the hum that motivated the gate is louder than the speech it
    was protecting. The room level is still worth knowing -- it is how a
    capture is read afterwards -- so the gate sees every frame and decides
    none of them.
    """

    def __init__(self, inner: FrameClassifier, gate: EnergyGate) -> None:
        self._inner = inner
        self.gate = gate

    def __call__(self, frame: bytes) -> bool:
        self.gate.observe(frame_rms(frame))
        return self._inner(frame)

    def set_speech_active(self, active: bool) -> None:
        self.gate.set_speech_active(active)
        if isinstance(self._inner, SpeechAware):
            self._inner.set_speech_active(active)

    def summary(self) -> str:
        inner = self._inner
        described = (
            inner.summary() if hasattr(inner, "summary") else "vad=unknown"
        )
        return f"{described} {self.gate.levels()}"


class EnergyGatedClassifier:
    """A voicing classifier that additionally requires audible loudness."""

    def __init__(self, inner: FrameClassifier, gate: EnergyGate) -> None:
        self._inner = inner
        self.gate = gate

    def __call__(self, frame: bytes) -> bool:
        # The inner detector adapts to every frame it sees, so it is always
        # consulted; only the verdict is gated.
        voiced = self._inner(frame)
        return self.gate.admits(frame_rms(frame)) and voiced


class VADEngine(StrEnum):
    SILERO = "silero"
    WEBRTC = "webrtc"


@dataclass(frozen=True, slots=True)
class VADConfig:
    sample_rate: int = 16_000
    frame_ms: int = 20
    mode: int = 2
    engine: VADEngine = VADEngine.SILERO
    silero: SileroConfig | None = None
    start_window_ms: int = 100
    start_voiced_ms: int = 60
    min_voiced_ms: int = 200
    end_silence_ms: int = 800
    start_timeout_ms: int = 10_000
    #: A room with a television in it never falls quiet for `end_silence_ms`,
    #: so a segment runs to this bound and arrives holding two speakers and
    #: the television. Measured at 10.2 s in that room. Shorter than a
    #: sentence someone would actually address to Andy, and the reply starts
    #: this many seconds after they began rather than whenever the room
    #: happens to pause.
    max_duration_ms: int = 10_000
    max_window_ms: int = 30_000
    energy: EnergyConfig | None = None

    def __post_init__(self) -> None:
        if self.sample_rate not in (8_000, 16_000, 32_000, 48_000):
            raise ValueError("WebRTC VAD requires an 8, 16, 32, or 48 kHz stream")
        if self.frame_ms not in (10, 20, 30):
            raise ValueError("WebRTC VAD frames must be 10, 20, or 30 ms")
        if not 0 <= self.mode <= 3:
            raise ValueError("WebRTC VAD mode must be between 0 and 3")
        timing_fields = {
            "start_window_ms": self.start_window_ms,
            "start_voiced_ms": self.start_voiced_ms,
            "min_voiced_ms": self.min_voiced_ms,
            "end_silence_ms": self.end_silence_ms,
            "start_timeout_ms": self.start_timeout_ms,
            "max_duration_ms": self.max_duration_ms,
            "max_window_ms": self.max_window_ms,
        }
        invalid_timings = [
            name
            for name, value in timing_fields.items()
            if value <= 0 or value % self.frame_ms != 0
        ]
        if invalid_timings:
            raise ValueError(
                "VAD timings must be positive frame multiples: "
                + ", ".join(invalid_timings)
            )
        if self.start_voiced_ms > self.start_window_ms:
            raise ValueError("start_voiced_ms cannot exceed start_window_ms")
        if self.start_voiced_ms > self.min_voiced_ms:
            raise ValueError("start_voiced_ms cannot exceed min_voiced_ms")
        if self.start_timeout_ms > self.max_window_ms:
            raise ValueError("start_timeout_ms cannot exceed max_window_ms")
        if self.max_duration_ms > self.max_window_ms:
            raise ValueError("max_duration_ms cannot exceed max_window_ms")
        if self.min_voiced_ms > self.max_duration_ms:
            raise ValueError("min_voiced_ms cannot exceed max_duration_ms")


class UtteranceDetector:
    """Streaming PCM16 utterance detector with deterministic time bounds."""

    def __init__(
        self,
        config: VADConfig | None = None,
        *,
        classifier: FrameClassifier | None = None,
        gate: EnergyGate | None = None,
        silero_model: SileroModel | None = None,
    ) -> None:
        self.config = config or VADConfig()
        self._frame_bytes = (
            self.config.sample_rate * self.config.frame_ms // 1_000 * 2
        )
        self._start_window_frames = max(
            1, self.config.start_window_ms // self.config.frame_ms
        )
        self._start_voiced_frames = max(
            1, self.config.start_voiced_ms // self.config.frame_ms
        )
        self._min_voiced_frames = max(
            1, self.config.min_voiced_ms // self.config.frame_ms
        )
        self._end_silence_frames = max(
            1, self.config.end_silence_ms // self.config.frame_ms
        )
        self._start_timeout_frames = max(
            1, self.config.start_timeout_ms // self.config.frame_ms
        )
        self._max_duration_frames = max(
            1, self.config.max_duration_ms // self.config.frame_ms
        )
        self._max_window_frames = max(
            1, self.config.max_window_ms // self.config.frame_ms
        )
        self.gate: EnergyGate | None = None
        if classifier is not None:
            self._classifier: FrameClassifier = classifier
        else:
            self.gate = gate if gate is not None else EnergyGate(
                self.config.energy
            )
            self.gate.begin_window()
            if self.config.engine is VADEngine.SILERO:
                if silero_model is None:
                    raise ValueError(
                        "the silero engine needs a loaded SileroModel"
                    )
                self._classifier = MeasuredClassifier(
                    SileroClassifier(silero_model, self.config.silero),
                    self.gate,
                )
            else:
                self._classifier = EnergyGatedClassifier(
                    WebRtcClassifier(
                        sample_rate=self.config.sample_rate,
                        mode=self.config.mode,
                    ),
                    self.gate,
                )
        self._speech_aware = (
            self._classifier
            if isinstance(self._classifier, SpeechAware)
            else None
        )
        self.reset()

    @property
    def capture_summary(self) -> str:
        """What this capture measured, for the line that records the turn."""
        classifier = self._classifier
        if hasattr(classifier, "summary"):
            return classifier.summary()
        if self.gate is not None:
            return self.gate.summary()
        return "vad=scripted"

    @property
    def speech_started(self) -> bool:
        return self._speech_started

    @property
    def has_transcribable_speech(self) -> bool:
        return (
            self._speech_started
            and self._voiced_frames >= self._min_voiced_frames
        )

    def _set_speech_active(self, active: bool) -> None:
        if self._speech_aware is not None:
            self._speech_aware.set_speech_active(active)
        elif self.gate is not None:
            self.gate.set_speech_active(active)

    def reset(self) -> None:
        self._set_speech_active(False)
        self._pending = bytearray()
        self._recent: deque[bool] = deque(maxlen=self._start_window_frames)
        self._frames = 0
        self._speech_frames = 0
        self._voiced_frames = 0
        self._silent_frames = 0
        self._candidate_started = False
        self._speech_started = False
        self._finished = False

    def push(self, pcm16: bytes) -> tuple[VADDecision, ...]:
        if self._finished or not pcm16:
            return ()
        self._pending.extend(pcm16)
        decisions: list[VADDecision] = []

        while len(self._pending) >= self._frame_bytes and not self._finished:
            frame = bytes(self._pending[: self._frame_bytes])
            del self._pending[: self._frame_bytes]
            voiced = self._classifier(frame)
            self._frames += 1

            if not self._speech_started:
                if not self._candidate_started:
                    self._recent.append(voiced)
                    if sum(self._recent) >= self._start_voiced_frames:
                        self._candidate_started = True
                        self._voiced_frames = sum(self._recent)
                        self._silent_frames = 0
                        self._recent.clear()
                elif voiced:
                    self._voiced_frames += 1
                    self._silent_frames = 0
                else:
                    self._silent_frames += 1

                if self._candidate_started:
                    if self._voiced_frames >= self._min_voiced_frames:
                        self._speech_started = True
                        self._silent_frames = 0
                        self._set_speech_active(True)
                        decisions.append(VADDecision.SPEECH_STARTED)
                    elif self._silent_frames >= self._end_silence_frames:
                        self._candidate_started = False
                        self._voiced_frames = 0
                        self._silent_frames = 0
                        self._recent.clear()

                if (
                    not self._candidate_started
                    and self._frames >= self._start_timeout_frames
                    and not any(self._recent)
                ):
                    self._finished = True
                    decisions.append(VADDecision.NO_SPEECH_TIMEOUT)
                    break
            else:
                if voiced:
                    self._voiced_frames += 1
                    self._silent_frames = 0
                else:
                    self._silent_frames += 1
                if (
                    self.has_transcribable_speech
                    and self._silent_frames >= self._end_silence_frames
                ):
                    self._finished = True
                    decisions.append(VADDecision.SPEECH_ENDED)
                    break

            if self._speech_started:
                self._speech_frames += 1
                if self._speech_frames >= self._max_duration_frames:
                    self._finished = True
                    decisions.append(VADDecision.MAX_DURATION)
                    break
            if self._frames >= self._max_window_frames:
                self._finished = True
                decisions.append(
                    VADDecision.MAX_DURATION
                    if self.has_transcribable_speech
                    else VADDecision.NO_SPEECH_TIMEOUT
                )
                break

        return tuple(decisions)

    def finish(self) -> VADDecision:
        self._finished = True
        if self.has_transcribable_speech:
            return VADDecision.SPEECH_ENDED
        return VADDecision.NO_SPEECH_TIMEOUT
