# Reference findings

## Source roles

| Source | Revision | Authority in Andy |
|---|---|---|
| `../StackChan` | `b72b3ed` | Factory interaction and product behavior |
| `../esphome-yaml` | `238ba9825e7874d5626709631dae6be92e861b17` | CoreS3 power, expander, codec, display, camera, and servo components |
| `../dotty-stackchan` | `5421b4c` | Community application and service-separation patterns |
| `../Will-Robot` | local files | This unit's servo calibration and observed hardware failure modes |
| `n-IA-hane/esphome-audio-stack` | `d03a546051d80bf263ba85c465e2db7224448abc` | Shared-I2S microphone and speaker owner |

Production firmware imports the pinned vendor board components in
`firmware/packages/board.yaml`, the pinned servo components in
`firmware/packages/motion.yaml`, and the pinned `esp_audio_stack` component in
`firmware/packages/audio.yaml`. Sibling directories remain read-only.

## Hardware conclusions

- CoreS3 microphone input and AW88298 output share one physical I2S clock set.
  Reliable bidirectional audio requires one component to own RX and TX.
- AW9523B port 0 uses push-pull mode. P0_2 releases AW88298 reset and the
  amplifier needs setup time before its first I2C transaction.
- The vendor AW88298 driver's `Initialized: NO` field is not an acceptance
  signal. Successful setup traffic, native playback state, and room audio are
  the useful evidence.
- PY32 pin 0 controls the servo motor rail independently of servo UART data.
- USB serial access resets this CoreS3. Routine logging and control therefore
  use encrypted native API over Wi-Fi.
- The internal shared I2C bus is reliable at 100 kHz. Production keeps
  GPIO12/GPIO11 at exactly that frequency.
- Servo calibration is unit-specific. Only `../Will-Robot` defines the
  offsets, conversion, range, speed, and safety values used by production.
- The pitch envelope is asymmetric and must not be probed toward a mechanical
  stop.
- The GC0308 camera pins and vendor configuration are known. Release `0.4.0`
  instantiates the camera in its second deployment cycle.

## Audio conclusions

- The ESPHome native voice-assistant subscription is the real microphone path.
  A standalone application WebSocket does not exercise firmware capture,
  playback, or device lifecycle.
- Production `esp_audio_stack` owns standard I2S at 48 kHz, consumes the ES7210
  right channel, performs DC correction, and emits 16 kHz mono capture.
- Production does not run an AEC post-processor. Firmware stops capture and
  reports a pause counter before Andy's speaker starts, so the ASR stream never
  includes Andy's own response.
- Kokoro output cannot be assumed to match a fixed rate. The Python adapter
  validates uncompressed PCM16 and normalizes to 24 kHz before ESPHome fetches
  the WAV, which is a passthrough for Kokoro's own 24 kHz output.
- The production speaker path decodes at 24 kHz and converts to the fixed 48 kHz
  hardware rate through the ESPHome resampler speaker.
- AW9523B P1_7 is `BOOST_EN`, the CoreS3 5 V boost converter, not an
  amplifier enable. The AW88298 and the 1 W speaker work without it, and the
  body's LED strip draws from it, so it is held on with `BUS_OUT_EN`.
- TTS media is a bounded, short-lived in-memory asset. The encrypted native API
  carries its URL; HTTP serves only that WAV.
- Andy reaches the server only through WireGuard, which hairpins through the
  cloud router at a measured 243 ms round trip against 2-13 ms on the LAN. Media
  transport must be sized for that: the device banks one second of audio before
  playback, and the server does not rate limit its writes. A 128 ms prebuffer
  and 1 KiB writes paced every 15 ms both sit below one round trip and produce
  continuous dropouts that are indistinguishable from a firmware fault.

## Turn-management conclusions

- A wake word is unnecessary for production. Continuous firmware capture plus
  server semantic classification gives more natural interaction.
- WebRTC VAD is a segmentation aid, not the authority for conversational
  meaning. GLM-5.2 can ignore nonsensical ASR, retain an incomplete fragment, or
  end context based on text.
- Ambient speech must not grow the prompt indefinitely. Production bounds
  audio, fragments, history, provider timeouts, and silence expiry.
- Raw VAD is too early to cancel another turn. Only a completed non-empty newer
  transcript can supersede reasoning for an older transcript.
- A no-speech capture sends `RUN_END` directly. This closes the firmware run
  without placing the device in a response-waiting state.
- Empty ASR is normal room behavior and must not increment device errors.
- Model output needs a strict decision protocol, bounded repair, an allowlist,
  trusted telemetry, and deterministic safety enforcement. Model intelligence
  does not replace these controls.
- Exact calibrated commands benefit from a deterministic semantic fast path.
  This removes cloud wording variance from release-critical commands while
  retaining GLM-5.2 for ambiguous and conversational language.

## Motion conclusions

- Movement is a validated application command, not a free-form language-model
  trajectory.
- The vendor and community projects justify a vocabulary richer than simple
  axis tests: gaze, nod, shake, bow, greeting, celebration, scan, and dance.
- Every program is a sequence of fixed firmware poses. Neither the LLM nor a
  transcript can provide an angle, step, speed, bound, keyframe, or button.
- Exact 30-degree left, right, and up language maps to calibrated gaze
  programs. Other directional angles fail closed.
- Each pose uses non-blocking travel-time supervision, alternating-axis
  feedback, confirmed stall detection, tracking validation, verified torque
  release, and rail power-off.
- Server completion checks the exact expected target, start/completion/fault
  counter deltas, tracking tolerance, and torque `0/0`.
- Motion, listening, and reasoning can progress concurrently. Capture and
  Andy's own speech remain mutually exclusive.
- A new motion cancels an active program through emergency stop. API loss,
  shutdown, timeout, fault, or rejection leaves the servos torque-free and the
  rail off.

## Observation conclusions

- C200 video is the release visual authority for externally visible movement
  and face state.
- C200 room audio proves that an onboard response entered the room only when an
  isolated post-stimulus transcript contains the expected response words.
- Wi-Fi ESPHome logs prove internal targets, counters, errors, torque, rail
  state, and reconnect behavior.
- Server journal and HTTP snapshots prove transcript processing, action
  authorization, provider readiness, and final application state.
- A robust physical conclusion correlates the applicable channels rather than
  inferring one from another.
