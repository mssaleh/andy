# Packaged models

## `silero_vad.onnx`

Silero VAD, release `v6.2.1`, MIT licensed, copyright 2020-present Silero Team.
Taken verbatim from `snakers4/silero-vad` at
`src/silero_vad/data/silero_vad.onnx`.

SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.

The model is vendored rather than downloaded. Server promotion builds an
isolated candidate and rolls back when it is not healthy; a model fetched at
deploy time would put a network dependency inside that window, and a model
fetched at first use would put it inside the first utterance.

The `silero-vad` distribution is not a dependency: it pulls `torch` and
`torchaudio`, which this server has no other use for. Only `onnxruntime` and
this file are needed.

### Contract

The published wrapper is the authority on how the model is called, and it is
not obvious from the signature alone:

- exactly 512 samples per chunk at 16 kHz;
- the previous chunk's last 64 samples are prepended, so the tensor is 576
  wide, and the first chunk of an utterance is prepended with 64 zeros;
- `state` is float32 `[2, batch, 128]`, carried from the `stateN` output;
- `sr` is an int64 scalar.

Feeding 512 samples without the context runs without error and returns a
probability near zero for speech, which looks like a silent room rather than a
misuse.
