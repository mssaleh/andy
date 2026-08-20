# Verification gates

## Release status

Firmware and server are both `0.5.0`, deployed separately. They only have to
match when the firmware itself changed; a reboot spent rewriting a version
string buys nothing.

The device runs passive voice interaction, a state-aware face and status ring,
bounded named motion, and the full peripheral set: battery and body power, the
12-LED ring, ambient light and proximity, infrared, head and screen touch,
inertial sensing, and the camera. Onboard speech is accepted: a reply spoken
through the AW88298 was recorded in the room by the C200 and transcribed
correctly by three independent recognisers.

| Gate | Status | Current evidence |
|---|---|---|
| Server behavior | Pass | All 211 Python 3.12 tests pass, covering the neural detector, the agent seam, the vision provider, and the deterministic control API |
| Firmware configuration | Pass | ESPHome 2026.8.0 production config is valid and the verified robot runs it |
| WireGuard production path | Pass | AGX `.3` has an established native-API session to Andy `.2` through the configured peer |
| Provider and deployment readiness | Pass | Recogniser, Kokoro, GLM-5.2, encrypted device transport, and motion readiness are health-gated; the detector is reported and deliberately not gated |
| Voice activity detection | Pass | In 45 s of a live room the neural detector opened no utterance where the spectral one opened four, and it admitted speech at RMS 244, below the level the loudness gate had settled on |
| Passive listening and capture pause | Pass | The physical canary recorded three capture pauses, three resumptions, zero voice errors, and no speech detection during announcement lifecycles |
| Acoustic self-speech exclusion | Pass | Capture pauses precede every announcement and no speech is detected while Andy speaks |
| Onboard speech | Pass | A reply spoken in the room transcribed identically through `whisper_trt small.en`, `faster-whisper-small` and `faster-whisper-large-v3-turbo` |
| Named motion and safety | Pass | Three programs completed with zero faults, each ending `torque released; servo rail off` |
| Calibrated semantic routing | Pass | Exact release phrases and unsupported-angle behavior are deterministic and regression-tested |
| Compound requests | Pass | A request naming a movement and a reminder sets the reminder and names the movement; the timer is on disk and the tool call is in the log |
| Claimed actions | Pass | An answer that promises a reminder without calling the tool that sets one is refused and retried |
| Camera honesty | Pass | A frame leaving the robot raises `camera_in_use` and a mark on the face from the camera's own callback, and clears 2.7 s later; the redraw is interlocked against motion and moved out of the camera's operation window, taking it from 268 ms to 113 ms |
| Device log volume | Pass | The firmware logger is `INFO`: debug and config lines are compiled out, saving 26 KB of flash and removing 187 debug lines per 50 s from the tunnel, while every counter the canary matches remains an `ESP_LOGI` and the client-side state lines are unaffected |
| Connectors | Pass | The configuration is parsed, handed to the MCP client library, dialled over stdio against a server that really runs, and its tool called and answered; credentials never appear in a description |
| Knowing the time and itself | Pass | Date, time, part of the day, daylight, next sunrise and sunset, time awake, warmth, head pose and connection are in front of the model every turn; motor temperature, power, memory, faults and orientation are behind `check_myself` |
| Knowing where it is | Pass | The robot looks up its own position on boot, retries each minute until that boot has an answer, refreshes every three hours, and keeps the position in flash; it reported `Sharjah` with sunrise 05:54 and sunset 18:48 within ten seconds of coming back |
| Not knowing where it is | Pass | Before the first answer the sun readings are withheld at the source and ignored again by the server, so the 09:59 sunrise computed for latitude zero never reaches the model; the clock still names the part of the day |
| Part of the day | Pass | Taken from the sun's measured elevation on the robot rather than from the hour, so a bright evening and a dark one are distinguishable |
| Looking | Pass | One frame from the robot's own camera crossed the tunnel and was answered locally by the detector, reporting correctly that nobody was present |

Physical evidence for onboard speech and motion was collected during this pass
from the C200 rig. The remaining physical work is a full release canary, which
needs renewed explicit authorization because it is audible and moves the robot.

## Evidence rules

- Tell the user immediately before sound, physical movement, robot reboot,
  firmware deployment, or production server restart.
- Never use serial or USB logging. Device logs come from the encrypted ESPHome
  API over Wi-Fi.
- Run `./tools/andy-host-check` before a physical trial.
- Count failed physical attempts toward the three-to-five-cycle limit.
- Stop after five cycles and close remaining defects with deterministic tests
  and already-recorded evidence.
- A physical claim requires the applicable C200 video, C200 room audio, Wi-Fi
  telemetry, and server evidence. No single channel proves the entire path.
- A canary exit code is not a visual review. Inspect every generated
  `visual-*.jpg` contact sheet before reporting a release pass.
- `Announcement finished`, speaker `PLAYING`, a media HTTP 200, and waveform
  energy are lifecycle evidence only. Intelligible onboard output requires a
  C200 response transcript containing the command-specific expected words.

| Channel | Required artifact and gate | Establishes | Does not establish |
|---|---|---|---|
| C200 video | `observation.mkv`, valid 1080p/10 fps stream, and four inspected 20-frame `visual-*.jpg` sheets | Externally visible face, look-right, nod, dance, and final pose | Servo torque, rail state, or spoken audio |
| C200 room audio | Four `response-*.wav` clips under 30 seconds and `response-*.json` files passing `andy-room-audio-check` | The expected Andy reply physically entered the room | Which internal decoder or amplifier state produced it |
| Encrypted Wi-Fi log | `device.log` with exact counters, target tracking, zero errors, torque `0/0`, and rail off | Firmware lifecycle and physical actuator telemetry | Audible speech or externally visible choreography |
| Server journal and HTTP | Non-empty `server.log`, exact decision/synthesis/action counts, and before/after JSON snapshots | ASR acceptance, routing, TTS creation, authorization, completion, and provider/device readiness | Delivery through Andy's speaker or visible motion |

## Gate 1: server behavior

Run:

```bash
./tools/uv run --project server --python 3.12 --extra dev pytest -q
```

Pass criteria:

- continuous capture and no-speech windows always return to a renewable state;
- empty ASR is routine and does not emit a device error;
- raw VAD cannot cancel pending ASR;
- only a completed non-empty newer transcript cancels stale reasoning;
- provider timeouts and failures leave the next capture usable;
- the model protocol fails closed and receives at most one repair call;
- conversation history, pending fragments, audio, and media storage are
  bounded;
- context clears after at least 15 seconds of silence;
- explicit sleep stops passive capture;
- TTS failure prevents motion dispatch;
- every motion stays inside the enum allowlist;
- the exact three release phrases have deterministic routes;
- the exact phrase “turn your head to the right by 30 degrees” resolves to
  `look_right` even if a model would ask for confirmation;
- an unsupported angle cannot reach the LLM or motion executor;
- incidental mentions of motion remain with semantic classification;
- action counters preserve completed motion state across ambient decisions;
- target, counter, fault, tracking, torque, and catalog validation are tested.

The suite imports the same application, coordinator, providers, transport,
action policy, and motion controller used in production.

## Gate 2: firmware

Validate:

```bash
./tools/esphome config firmware/andy.yaml
```

Compile when firmware changes:

```bash
./tools/esphome compile firmware/andy.yaml
```

Pass criteria:

- project identity is `andy.voice-agent` version `0.5.0`;
- internal I2C resolves to exactly 100,000 Hz on GPIO12/GPIO11;
- logger baud resolves to zero;
- ESP-IDF primary and secondary consoles remain disabled;
- the servo UART remains isolated on GPIO6/GPIO7 at 1 Mbaud;
- continuous voice capture has `use_wake_word: false`;
- the microphone uses direct right-channel audio with no AEC processor;
- a capture-pause button and counter gate every announcement;
- only fixed calibrated servo targets are present;
- shutdown and disconnect invoke torque-off, rail-off behavior;
- WireGuard uses `10.0.0.2` and the single configured peer;
- external components remain pinned to immutable revisions.

The current compiled OTA binary is 1,231,568 bytes; its unpadded image content
is 1,231,455 bytes.

## Gate 3: deployment readiness

`GET /health` passes only when:

- Whisper ASR health is true;
- Kokoro TTS health is true;
- GLM-5.2 appears in the model catalog;
- the robot-facing media base is `http://10.0.0.3:8900`;
- the exact robot is connected through encrypted native API;
- every required motion entity and telemetry state is bound;
- named motion is enabled in production.

`GET /motions` must expose exactly 13 programs with 2 look-right steps, 4 nod
steps, and 8 dance steps. `GET /actions` must report connected/ready device
state, current action state, durable counters, and live safety telemetry.

The AGX interface is `10.0.0.3/24`, its route to Andy selects source `.3`,
and the production TCP session terminates at `10.0.0.2:6053`.

`./tools/andy-server-promote --apply` renders the exact environment from the
ignored root `.env`, the native-API key in `firmware/secrets.yaml`, and
`server/deploy/production.env.example`. It transfers only the mode-`0600`
rendered file, builds a clean candidate with a project-local Python 3.12 uv
environment, atomically replaces production, and restores the preceding
production tree if these gates do not become ready. The deployed media base is
`http://10.0.0.3:8900`, which remains reachable by Andy away from the home LAN.

## Gate 4: passive voice and onboard output

Current status: passive capture, capture pause, failure recovery, and capture
resumption pass. Successful onboard media playback and acoustic self-speech
exclusion lack physical proof. The available C200 response windows fail the
semantic room-audio gate.

Pass criteria:

- firmware continuously renews capture without a wake word;
- WebRTC VAD ends speech after 800 ms and bounds each window;
- room speech reaches non-empty ASR;
- unrelated or nonsensical speech can be ignored without blocking later turns;
- incomplete fragments can wait for a later transcript;
- only explicit “stop listening” semantics disable passive capture;
- capture stops and its counter advances before every announcement;
- no speech detection occurs while Andy is announcing;
- announcement start, finish, amplifier start, and amplifier idle complete;
- passive listening resumes after output;
- a reply-only arithmetic prompt produces `four` before any motion is permitted;
- each post-stimulus C200 response clip contains the expected semantic pair:
  `look` + `right`, `yes` + `nod`, or `dance` + `time`;
- zero voice errors, unexpected disconnects, or device resets occur.

The production audio path is direct 16 kHz mono microphone input and normalized
48 kHz PCM16 output. This gate does not depend on acoustic echo cancellation.
The response clip begins two seconds before HDMI playback returns, so a reply
that starts while the prompt stream drains is retained. The semantic pairs are
absent from the corresponding prompts, which prevents HDMI stimulus audio from
satisfying the onboard-response gate.

## Gate 5: named motion and safety

After the reply-only onboard-speech gate passes, the production physical
evidence contains:

- three accepted actions: `look_right`, `nod_yes`, and `dance`;
- three completed actions and zero action failures or rejections;
- exactly 14 movement starts and 14 movement completions;
- zero motion faults and zero API disconnects;
- look-right target `552/620` followed by home `466/620`;
- nod sequence `466/577`, `466/705`, `466/577`, `466/620`;
- dance sequence left, right, up, right, left, down, up, home;
- final tracking error no greater than 9 steps in the observed sequence;
- final torque `0/0` and servo rail off after every pose.

C200 frames visibly show the 30-degree yaw change, the vertical nod poses, the
alternating dance poses, and the final centered pose. The Wi-Fi timestamps align
those frames with each fixed target and completion packet.

## Gate 6: calibrated semantic routing

The release prompt set is:

1. “Please turn your head to the right by thirty degrees.”
2. “Please say yes with your head.”
3. “Please show me a dance.”

All three resolve before GLM-5.2. The router also accepts punctuation,
politeness, `Andy` prefixes, the degree symbol, and `ten`/`thirty` number words
for its explicitly registered commands. It matches the complete normalized
request, so a documentary or background sentence containing “look right” does
not actuate Andy.

GLM-5.2 remains the semantic controller for ambiguous language, ambient speech,
incomplete fragments, conversational references, context closure, and ordinary
answers. Its prompt includes the exact catalog and instructs it to dispatch a
matching calibrated program without confirmation and never approximate an
unsupported angle.

## Production read-only checks

These checks do not produce sound or motion:

```bash
curl --fail http://192.0.2.20:8900/health | jq
curl --fail http://192.0.2.20:8900/actions | jq
curl --fail http://192.0.2.20:8900/motions | jq
./tools/andy-logs
```

Safe idle requires:

- `motion_active: false`;
- `motion_inhibited: false`;
- `motion_faults: 0`;
- no active program;
- a motion state ending in torque `0/0` or the explicit rail-off idle state;
- a listening or speech-detected voice state when passive capture is awake.
