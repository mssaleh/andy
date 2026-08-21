# Andy

Andy is an M5Stack StackChan K151/CoreS3 robot with ESPHome firmware and a
Python 3.12 voice-agent server at LAN address `192.0.2.20` and WireGuard
address `10.0.0.3`. Andy listens passively with no wake word, decides on the
server, wears one of thirty-six emotions, moves inside a closed catalog of safe
two-axis poses, keeps memories, fires reminders, and looks at the room when
asked.

Onboard speech is accepted: a reply spoken through the AW88298 was recorded in
the room by the C200 and transcribed correctly by three independent
recognisers.

The production runtime is designed for natural conversation:

1. ESPHome continuously streams 16 kHz mono microphone audio while Andy is not
   speaking.
2. A neural voice activity detector closes bounded utterances and a
   recogniser produces text.
3. An exact calibrated-command router handles unambiguous motion requests.
   GLM-5.2 classifies all other non-empty transcripts as ambient speech,
   incomplete speech, conversation, context closure, motion, or explicit sleep.
4. Kokoro speech is normalized to PCM16 at 48 kHz and played by Andy's AW88298
   speaker.
5. A capture-pause handshake stops the microphone before playback, so Andy
   never transcribes his own voice.
6. Bounded motion, listening, and agent work run independently. Every pose
   finishes with verified torque release and the servo rail off.

No wake word is configured in production. Conversation context is bounded and
clears after at least 15 seconds of silence. Only an explicit request to stop
listening puts Andy to sleep.

## Safety boundary

The LLM may select only one named action. It cannot supply angles, servo steps,
speed, safety limits, entity names, poses, or choreography. Exact 30-degree
left, right, and up requests route directly to their calibrated programs;
unsupported angles fail closed. The fixed physical targets and motion safety
come only from the measurements in `../Will-Robot`.

Production uses:

- internal I2C on GPIO12/GPIO11 at exactly 100 kHz;
- a dedicated GPIO6/GPIO7 servo UART at 1 Mbaud;
- encrypted ESPHome native API transport over Wi-Fi;
- logger baud `0` with all ESP-IDF consoles disabled;
- battery-backed BM8563 time for independent WireGuard startup, refreshed by
  SNTP or the encrypted native API;
- MAC `AA:BB:CC:DD:EE:FF`, LAN recovery address `192.0.2.10`, and
  WireGuard production address `10.0.0.2`.

USB serial is not an observation path because it resets this CoreS3.

## Repository layout

- `AGENTS.md`: mandatory safety, isolation, release-budget, and observation
  rules for every coding session.
- `firmware/andy.yaml`: the production `andy.voice-agent` image.
- `firmware/diagnostics.yaml`: the bench bring-up image. It carries the same
  board, audio, display, and motion packages as production and adds an I2C
  inventory, a power-rail assertion, and live microphone levels. It has no
  WireGuard tunnel and is not a deployment target.
- `firmware/packages/`: `board`, `network`, `audio`, `display`, `camera`, and
  `motion` — the shared implementation both images are composed from.
- `server/src/andy/`: native-API bridge, VAD/turn manager, providers, semantic
  action policy, motion controller, vision, and HTTP application.
- `services/`: the small HTTP services that run inside the inference containers
  on the AGX, described in [`services/README.md`](services/README.md).
- `server/tests/`: production-path unit and integration tests.
- `docs/architecture.md`: component ownership and concurrency model.
- `docs/hardware-contract.md`: electrical and mechanical limits.
- `docs/motion-vocabulary.md`: pose and named-program contract.
- `docs/observation-rig.md`: C200, HDMI, room-audio, and Wi-Fi evidence setup.
- `docs/verification.md`: current release gates and evidence rules.
- `docs/reference-findings.md`: authoritative conclusions from vendor,
  community, and sibling sources.
- `knowledge/`: permanent read-only vendor and hardware reference archive.
- `tools/`: reproducible checks, deployments, and evidence collectors described
  in [`tools/README.md`](tools/README.md).

The CoreS3 onboard camera is configured and is how Andy looks at the room, one
requested frame at a time. It is not a verification channel: a camera cannot
show what the robot carrying it did. The Anker C200 remains the external visual
evidence channel.

## Connectors

Andy attaches MCP servers as extra toolsets. `ANDY_MCP_SERVERS` takes either a
comma-separated list of Streamable HTTP URLs, or the same `mcpServers` object
every other MCP client reads, which is what carries a command, an environment,
or a URL with an authorization header:

```json
{"mcpServers": {
  "notes": {"command": "python3", "args": ["-m", "notes_server"]},
  "house": {"url": "https://example.invalid/api/mcp",
            "headers": {"Authorization": "Bearer TOKEN"}}
}}
```

A connector's credentials live in the rendered production environment beside
the device key, never in this repository, and never in a log: `GET /agent`
lists what is attached and where it points, and nothing else.

## Local verification

All Python work uses repository-local uv state and Python 3.12:

```bash
./tools/uv sync --project server --python 3.12 --extra dev
./tools/uv run --project server --python 3.12 --extra dev pytest -q
./tools/esphome config firmware/andy.yaml
```

Compile only when firmware changes:

```bash
./tools/esphome compile firmware/andy.yaml
```

These commands do not flash the robot.

## Deployment

Production listens on both `192.0.2.20:8900` and WireGuard
`10.0.0.3:8900`. The server connects from WireGuard `10.0.0.3` to Andy at
`10.0.0.2`, and Andy fetches response audio from `10.0.0.3:8900`. Neither
direction depends on the home LAN, so Andy behaves the same wherever it is.
Firmware OTA uses the LAN recovery address. Andy reaches the tunnel only
through the WireGuard peer configured in firmware secrets. Deploy firmware
first and the server second:

```bash
./tools/andy-firmware-deploy --apply
./tools/andy-server-promote --apply
curl --fail http://192.0.2.20:8900/health
curl --fail http://192.0.2.20:8900/actions
curl --fail http://192.0.2.20:8900/motions
```

Firmware deployment verifies the exact MAC, device name,
and project identity immediately before Wi-Fi OTA. Server promotion renders the
exact production environment from the ignored root `.env`, the native-API key
in `firmware/secrets.yaml`, and the checked-in environment contract. It
transfers only the mode-`0600` rendered environment, builds an isolated Python
3.12 uv candidate, atomically replaces production, and restores the preceding
healthy production tree if GLM-5.2, providers, device identity, or motion
readiness fails. Root `.env` is the operator overlay and must provide a
non-empty `ANDY_LLM_API_KEY`; it is never copied as repository source.

## Closed-loop observation

The Anker C200 records 1080p video and 48 kHz stereo room audio. The S32B80P
HDMI sink supplies synthetic Kokoro prompts through a calibrated non-silent
warm-up. Encrypted ESPHome API logs provide internal state without touching
serial.

```bash
./tools/andy-host-check
./tools/andy-camera-setup
./tools/andy-observe 15
./tools/andy-logs
```

`./tools/andy-release-canary` is an audible physical test that first requires
an intelligible reply-only onboard-speaker result. Only then does it cover
look-right, nod, and dance across 14 safe pose executions. It
machine-transcribes isolated C200 response clips and creates per-command visual
contact sheets; all sheets must also be inspected before a release pass is reported. A release
implementation pass may use at most three to five physical cycles, including
failed cycles. Always warn the user immediately before sound, motion, robot
reboot, or server restart.

## Licence and credits

The source is MIT licensed. See `LICENSE`, which also covers the third-party
material that keeps its own terms.

Andy's faces are designed by [rawpixel.com / Freepik](https://www.freepik.com)
and used under a Freepik subscription. That credit travels with the artwork.

The reference documentation under `knowledge/` is M5Stack product documentation,
reproduced verbatim for the hardware this firmware drives.
