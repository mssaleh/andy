# Test fixtures

`speech_16k.wav` is 1.65 s of 16 kHz mono PCM16 speech, synthesised with the
deployment's own Kokoro voice saying "Andy, look to your right."

It exists because every other property of the neural detector can be asserted
against generated signals, and the one that cannot is whether it recognises a
person. A detector wired with the wrong state or context runs without error and
reports real speech at a probability near zero, which is indistinguishable from
a quiet room unless a test plays it something a person actually said.
