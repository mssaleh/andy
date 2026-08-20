from __future__ import annotations

from collections import deque

import pytest

import struct

from andy.vad import (
    EnergyConfig,
    EnergyGate,
    EnergyGatedClassifier,
    UtteranceDetector,
    VADConfig,
    VADDecision,
)


class ScriptedClassifier:
    def __init__(self, values: list[bool]) -> None:
        self.values = deque(values)

    def __call__(self, frame: bytes) -> bool:
        assert len(frame) == 640
        return self.values.popleft() if self.values else False


def detector(values: list[bool]) -> UtteranceDetector:
    return UtteranceDetector(
        VADConfig(
            frame_ms=20,
            start_window_ms=100,
            start_voiced_ms=60,
            min_voiced_ms=100,
            end_silence_ms=100,
            start_timeout_ms=200,
            max_duration_ms=1_000,
        ),
        classifier=ScriptedClassifier(values),
    )


def test_partial_frames_are_buffered() -> None:
    vad = detector([True] * 5)
    assert vad.push(b"\0" * 639) == ()
    assert vad.push(b"\0") == ()
    assert vad.push(b"\0" * 1_280) == ()
    assert vad.push(b"\0" * 1_280) == (VADDecision.SPEECH_STARTED,)


def test_speech_ends_after_minimum_voice_and_hangover() -> None:
    vad = detector([True] * 5 + [False] * 5)
    decisions = vad.push(b"\0" * 640 * 10)
    assert decisions == (
        VADDecision.SPEECH_STARTED,
        VADDecision.SPEECH_ENDED,
    )
    assert vad.has_transcribable_speech


def test_quiet_capture_times_out_without_speech() -> None:
    vad = detector([False] * 10)
    assert vad.push(b"\0" * 640 * 10) == (VADDecision.NO_SPEECH_TIMEOUT,)
    assert not vad.has_transcribable_speech


def test_finish_distinguishes_speech_from_noise() -> None:
    speech = detector([True] * 5)
    speech.push(b"\0" * 640 * 5)
    assert speech.finish() is VADDecision.SPEECH_ENDED

    noise = detector([True, False, False])
    noise.push(b"\0" * 640 * 3)
    assert noise.finish() is VADDecision.NO_SPEECH_TIMEOUT


def test_scattered_voiced_noise_never_becomes_an_utterance() -> None:
    values = [True, False, False] * 5
    vad = UtteranceDetector(
        VADConfig(
            frame_ms=20,
            start_window_ms=100,
            start_voiced_ms=60,
            min_voiced_ms=100,
            end_silence_ms=100,
            start_timeout_ms=400,
            max_duration_ms=1_000,
        ),
        classifier=ScriptedClassifier(values),
    )
    assert vad.push(b"\0" * 640 * 15) == ()
    assert vad.finish() is VADDecision.NO_SPEECH_TIMEOUT
    assert not vad.speech_started
    assert not vad.has_transcribable_speech


def test_short_candidate_rearms_instead_of_waiting_for_max_duration() -> None:
    vad = detector([True] * 3 + [False] * 17)

    assert vad.push(b"\0" * 640 * 20) == (VADDecision.NO_SPEECH_TIMEOUT,)
    assert not vad.speech_started
    assert not vad.has_transcribable_speech


def test_real_speech_can_follow_a_rejected_candidate() -> None:
    values = [True] * 3 + [False] * 5 + [True] * 5 + [False] * 5
    vad = detector(values)

    assert vad.push(b"\0" * 640 * len(values)) == (
        VADDecision.SPEECH_STARTED,
        VADDecision.SPEECH_ENDED,
    )
    assert vad.has_transcribable_speech


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_silence_ms": 0},
        {"start_window_ms": 101},
        {"start_voiced_ms": 120, "start_window_ms": 100},
        {
            "start_window_ms": 200,
            "start_voiced_ms": 120,
            "min_voiced_ms": 100,
        },
        {"start_timeout_ms": 1_200, "max_window_ms": 1_000},
        {"max_duration_ms": 2_000, "max_window_ms": 1_000},
    ],
)
def test_invalid_vad_timing_is_rejected(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        VADConfig(**overrides)


def test_energy_gate_tracks_the_quantile_it_promises() -> None:
    # A stream whose 90th percentile is known exactly: 90 frames at 100 and
    # 10 at 1000, repeated. The estimate must settle at the boundary.
    gate = EnergyGate(EnergyConfig(noise_initial=250, adapt_rate=0.01))
    stream = ([100] * 90 + [1_000] * 10) * 60
    for rms in stream:
        gate.admits(rms)
    above = sum(1 for rms in stream[-2_000:] if rms > gate.noise_level)
    assert 0.05 <= above / 2_000 <= 0.15


def test_energy_gate_threshold_scales_with_the_room() -> None:
    quiet = EnergyGate(EnergyConfig(min_speech_rms=0))
    loud = EnergyGate(EnergyConfig(min_speech_rms=0))
    for _ in range(20_000):
        quiet.admits(50)
        loud.admits(2_000)
    assert quiet.threshold < loud.threshold / 10


def test_energy_gate_holds_an_absolute_minimum_in_a_silent_room() -> None:
    gate = EnergyGate(EnergyConfig(noise_min=40, min_speech_rms=200))
    for _ in range(20_000):
        gate.admits(0)
    assert gate.noise_level == 40
    assert gate.threshold == 200
    assert not gate.admits(150)
    assert gate.admits(250)


def test_energy_gate_ignores_frames_while_speech_is_in_progress() -> None:
    """An utterance must not raise the bar it is being measured against."""
    gate = EnergyGate(EnergyConfig(min_speech_rms=0))
    for _ in range(20_000):
        gate.admits(120)
    settled = gate.noise_level

    gate.set_speech_active(True)
    for _ in range(5_000):
        gate.admits(4_000)
    assert gate.noise_level == settled

    gate.set_speech_active(False)
    gate.admits(4_000)
    assert gate.noise_level > settled


def test_energy_gate_climbs_to_a_room_louder_than_its_starting_guess() -> None:
    gate = EnergyGate(EnergyConfig(noise_initial=250, min_speech_rms=0))
    for _ in range(20_000):
        gate.admits(1_200)
    assert 900 <= gate.noise_level <= 1_300


def test_gated_classifier_requires_both_voicing_and_loudness() -> None:
    gate = EnergyGate(EnergyConfig(noise_initial=80, min_speech_rms=200))
    loud = struct.pack("<h", 1_000) * 320
    quiet = struct.pack("<h", 50) * 320
    assert EnergyGatedClassifier(lambda frame: True, gate)(loud)
    assert not EnergyGatedClassifier(lambda frame: False, gate)(loud)
    assert not EnergyGatedClassifier(lambda frame: True, gate)(quiet)


def test_utterance_is_bounded_from_speech_onset_not_window_open() -> None:
    config = VADConfig(
        frame_ms=20,
        start_window_ms=100,
        start_voiced_ms=60,
        min_voiced_ms=100,
        end_silence_ms=200,
        start_timeout_ms=400,
        max_duration_ms=400,
        max_window_ms=2_000,
    )
    # Silence first, so a window-based bound would truncate the speech that
    # follows it; the utterance must still get its full allowance.
    values = [False] * 10 + [True] * 40
    vad = UtteranceDetector(config, classifier=ScriptedClassifier(values))
    decisions = vad.push(b"\0" * 640 * 50)
    assert decisions == (VADDecision.SPEECH_STARTED, VADDecision.MAX_DURATION)
    assert vad.has_transcribable_speech


def test_window_accounting_resets_but_the_learned_room_does_not() -> None:
    gate = EnergyGate(EnergyConfig(noise_initial=300))
    for _ in range(300):
        gate.admits(120)
    learned = gate.noise_level
    assert gate.frames == 300

    gate.begin_window()
    assert gate.frames == 0
    assert gate.admitted == 0
    assert gate.peak_rms == 0
    assert gate.noise_level == learned


def test_window_summary_reports_the_measured_distribution() -> None:
    gate = EnergyGate(EnergyConfig(noise_initial=100, min_speech_rms=200))
    for rms in [100] * 90 + [1_000] * 10:
        gate.admits(rms)
    assert gate.percentile(0.50) == 100
    assert gate.percentile(0.99) == 1_000
    summary = gate.summary()
    assert "rms_p50=100" in summary
    assert "admitted=10/100" in summary


# --- the neural detector -------------------------------------------------

import wave
from pathlib import Path

from andy.vad import (
    MeasuredClassifier,
    SileroClassifier,
    SileroConfig,
    SileroModel,
    VADEngine,
    frame_rms,
)

FIXTURES = Path(__file__).parent / "data"
FRAME_BYTES = 640  # 20 ms of 16 kHz mono PCM16


def _model() -> SileroModel:
    return SileroModel()


def _frames(pcm: bytes) -> list[bytes]:
    return [
        pcm[i : i + FRAME_BYTES]
        for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES)
    ]


def _speech_pcm() -> bytes:
    with wave.open(str(FIXTURES / "speech_16k.wav")) as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        return handle.readframes(handle.getnframes())


def _tone_pcm(frequency: int, amplitude: int, seconds: float) -> bytes:
    import math

    count = int(16_000 * seconds)
    return b"".join(
        struct.pack(
            "<h",
            int(amplitude * math.sin(2 * math.pi * frequency * n / 16_000)),
        )
        for n in range(count)
    )


def _voiced_fraction(classifier, pcm: bytes) -> float:
    frames = _frames(pcm)
    voiced = sum(1 for frame in frames if classifier(frame))
    return voiced / max(1, len(frames))


def test_silero_hears_a_person() -> None:
    """The accept path, against audio a person actually produced.

    Wired with the wrong context or a state that is not carried between
    chunks, the model runs without error and reports this at a probability
    near zero. Only real speech distinguishes that from a silent room.
    """
    classifier = SileroClassifier(_model())
    assert _voiced_fraction(classifier, _speech_pcm()) > 0.5
    assert classifier.percentile(0.90) > 0.8


def test_silero_refuses_a_hum_that_is_louder_than_the_speech() -> None:
    """The case no loudness threshold can fix.

    Mains hum is voiced by a spectral measure and louder than a person, so a
    gate that admits the speech necessarily admits the hum. This is the whole
    reason the decision moved to a network.
    """
    hum = _tone_pcm(frequency=60, amplitude=8_000, seconds=2.0)
    speech = _speech_pcm()
    assert frame_rms(hum[:FRAME_BYTES]) > frame_rms(speech[len(speech) // 2:][:FRAME_BYTES])
    assert _voiced_fraction(SileroClassifier(_model()), hum) == 0.0


def test_silero_refuses_silence_and_broadband_noise() -> None:
    model = _model()
    silence = b"\0" * FRAME_BYTES * 50
    assert _voiced_fraction(SileroClassifier(model), silence) == 0.0

    noise = b"".join(
        struct.pack("<h", (n * 1_103_515_245 + 12_345) % 4_000 - 2_000)
        for n in range(16_000)
    )
    assert _voiced_fraction(SileroClassifier(model), noise) < 0.1


def test_silero_feeds_the_model_its_documented_chunk_and_context() -> None:
    """512 samples of audio behind 64 samples of the chunk before it."""

    class RecordingModel:
        def __init__(self) -> None:
            import numpy

            self._numpy = numpy
            self.widths: list[int] = []
            self.contexts: list[object] = []

        def initial_state(self):
            return self._numpy.zeros((2, 1, 128), dtype=self._numpy.float32)

        def initial_context(self):
            return self._numpy.zeros((1, 64), dtype=self._numpy.float32)

        def probability(self, chunk, state, context):
            import numpy

            padded = numpy.concatenate([context, chunk], axis=1)
            self.widths.append(padded.shape[1])
            self.contexts.append(padded[:, -64:].copy())
            return 0.9, state, padded[:, -64:]

    recorder = RecordingModel()
    classifier = SileroClassifier(recorder)
    # 2,560 samples is exactly five 512-sample chunks and eight 20 ms frames.
    for frame in _frames(b"\1\0" * 2_560):
        classifier(frame)

    assert recorder.widths == [512 + 64] * 5
    assert classifier.chunks == 5


def test_silero_carries_one_verdict_across_the_frames_between_chunks() -> None:
    """A 20 ms frame grid over a 32 ms model: no frame is left undecided.

    320 samples arrive per frame and the model consumes 512, so a chunk
    completes on some frames and not others. A frame that completes no chunk
    keeps the verdict of the last one that did, rather than reading as silence.
    """

    class ScriptedModel:
        def __init__(self, probabilities: list[float]) -> None:
            import numpy

            self._numpy = numpy
            self._probabilities = deque(probabilities)

        def initial_state(self):
            return self._numpy.zeros((2, 1, 128), dtype=self._numpy.float32)

        def initial_context(self):
            return self._numpy.zeros((1, 64), dtype=self._numpy.float32)

        def probability(self, chunk, state, context):
            probability = (
                self._probabilities.popleft() if self._probabilities else 0.0
            )
            return probability, state, context

    classifier = SileroClassifier(ScriptedModel([0.9, 0.1]))
    frame = b"\1\0" * 320

    # 320 samples: no chunk has completed, so there is nothing to report yet.
    assert classifier(frame) is False
    assert classifier.chunks == 0
    # 640 samples: one chunk of 512 completes and 128 samples carry over.
    assert classifier(frame) is True
    assert classifier.chunks == 1
    # 448 samples: still short of a chunk, so the previous verdict stands.
    assert classifier(frame) is True
    assert classifier.chunks == 1
    # 768 samples: the second chunk completes and replaces the verdict.
    assert classifier(frame) is False
    assert classifier.chunks == 2


def test_silero_holds_a_lower_bar_once_someone_is_speaking() -> None:
    classifier = SileroClassifier(
        _model(), SileroConfig(speech_threshold=0.9, keep_threshold=0.1)
    )
    assert classifier.threshold == pytest.approx(0.9)
    classifier.set_speech_active(True)
    assert classifier.threshold == pytest.approx(0.1)
    classifier.set_speech_active(False)
    assert classifier.threshold == pytest.approx(0.9)


@pytest.mark.parametrize(
    "overrides",
    [
        {"speech_threshold": 0.0},
        {"speech_threshold": 1.0},
        {"keep_threshold": 0.0},
        {"speech_threshold": 0.4, "keep_threshold": 0.5},
    ],
)
def test_invalid_silero_thresholds_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        SileroConfig(**overrides)


def test_measured_classifier_records_the_room_but_never_vetoes() -> None:
    """Loudness is measured and ignored, which is the point of the change."""
    gate = EnergyGate(EnergyConfig(noise_initial=80, min_speech_rms=30_000))
    quiet = struct.pack("<h", 40) * 320
    measured = MeasuredClassifier(lambda frame: True, gate)

    # The gate's own threshold would reject this frame outright.
    assert not gate.admits(frame_rms(quiet))
    assert measured(quiet) is True
    assert gate.frames > 0
    assert "rms_p50=" in measured.summary()


def test_measured_classifier_passes_speech_state_to_both_halves() -> None:
    gate = EnergyGate(EnergyConfig())
    classifier = SileroClassifier(_model(), SileroConfig(keep_threshold=0.2))
    measured = MeasuredClassifier(classifier, gate)

    measured.set_speech_active(True)
    assert classifier.threshold == pytest.approx(0.2)
    settled = gate.noise_level
    for _ in range(500):
        gate.observe(9_000)
    assert gate.noise_level == settled


def test_detector_reports_what_the_capture_measured() -> None:
    detector = UtteranceDetector(
        VADConfig(engine=VADEngine.SILERO), silero_model=_model()
    )
    detector.push(_speech_pcm())
    summary = detector.capture_summary
    assert "vad=silero" in summary
    assert "peak_speech=" in summary
    assert "rms_p90=" in summary


def test_silero_detector_segments_real_speech() -> None:
    detector = UtteranceDetector(
        VADConfig(engine=VADEngine.SILERO), silero_model=_model()
    )
    decisions = detector.push(_speech_pcm())
    assert VADDecision.SPEECH_STARTED in decisions
    assert detector.has_transcribable_speech


def test_silero_detector_hears_nothing_in_a_hum() -> None:
    detector = UtteranceDetector(
        VADConfig(engine=VADEngine.SILERO), silero_model=_model()
    )
    detector.push(_tone_pcm(frequency=60, amplitude=8_000, seconds=3.0))
    assert not detector.speech_started
    assert detector.finish() is VADDecision.NO_SPEECH_TIMEOUT


def test_silero_engine_without_a_model_fails_closed() -> None:
    with pytest.raises(ValueError):
        UtteranceDetector(VADConfig(engine=VADEngine.SILERO))


def test_webrtc_engine_remains_available_for_comparison() -> None:
    detector = UtteranceDetector(VADConfig(engine=VADEngine.WEBRTC))
    detector.push(_speech_pcm())
    assert detector.speech_started
    assert "admitted=" in detector.capture_summary
