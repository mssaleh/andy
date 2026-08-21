# Andy project instructions

## Scope and sources of truth

- This repository owns Andy's ESPHome production firmware, Python server,
  deployment scripts, and closed-loop verification tooling.
- `firmware/andy.yaml` is the production image and `firmware/diagnostics.yaml`
  is the bench image. Both are composed from `firmware/packages/`, so a change
  to a package reaches production. Diagnostics adds bench-only probes and
  carries the same WireGuard tunnel as production, so it must never run on a
  second device while Andy is up; it does not define production interaction
  behavior.
- Sibling repositories are read-only references. Do not import from or edit
  them.
- `knowledge/` is a permanent read-only reference archive. Never delete,
  rename, rewrite, or prune anything under it.
- `../Will-Robot` is authoritative only for this physical unit's servo offsets,
  angle-to-step conversion, measured travel envelope, speed, and motion safety
  observations. Do not rederive or widen them.
- Andy's interaction names, choreography, conversational behavior, and agent
  policy belong to this repository. Vendor and community projects are idea
  sources for those concerns.
- Documents state the present truth. Delete obsolete statements instead of
  retaining an edit narrative.

## Tool and Python isolation

- Python is 3.12 and runs only through `./tools/uv` with `--project firmware` or
  `--project server`.
- Do not invoke system Python, `pip`, `pipx`, a user-level virtual environment,
  or a user-level Python cache.
- `./tools/uv` keeps managed Python and uv caches in this repository.
  `./tools/esphome` keeps ESPHome and PlatformIO state here as well.
- Host observation utilities are shell tools: `ffmpeg`, `ffprobe`, `v4l2-ctl`,
  `wpctl`, `pw-play`, `curl`, `jq`, `ssh`, and `rsync`.
- `.env`, `firmware/secrets.yaml`, and any ignored deployment environment file
  are persistent secret sources. Never delete them during cleanup and never
  print their values.
- Put transient recordings, generated prompts, contact sheets, and logs in
  `/tmp`. Create persistent evidence only when an explicit result path is
  requested.

## Infrastructure boundaries

- The cloud WireGuard VPS/router is not an experimentation target. Before any
  command that changes it, explain the exact intended change and wait for the
  user's explicit approval. Read-only access also requires advance notice.
- The local development computer is not an experimentation target. Limit work
  on it to repository files and the established Andy observation and deployment
  tools. Do not change its packages, services, firewall, routes, interfaces, or
  system configuration, and do not use it for ad hoc network probes.
- Experimental host-side networking and containers are permitted only on the
  AGX-Orin. Firmware experiments are permitted only within the physical-cycle
  budget and the notification requirements below.

## Production identity and hardware

- Production firmware and server version: `0.5.0`. They are deployed
  separately and only have to match when the firmware itself changed; a reboot
  spent rewriting a version string buys nothing.
- Robot: M5Stack StackChan K151/CoreS3.
- Robot MAC: `AA:BB:CC:DD:EE:FF`.
- Robot LAN recovery and OTA address: `192.0.2.10`.
- Robot WireGuard production address: `10.0.0.2`.
- Production server: `192.0.2.20:8900`.
- Production server WireGuard address: `10.0.0.3`.
- Robot-facing response media: `http://10.0.0.3:8900`.
- Andy reaches the production server only through the WireGuard peer
  configured in firmware secrets. There is no LAN fallback path.
- The AGX owns the `10.0.0.3` WireGuard interface.
- ESPHome project identity: `andy.voice-agent`.
- ESPHome version: `2026.8.0`.
- Internal I2C is GPIO12 SDA and GPIO11 SCL at exactly `100000 Hz`.
- Servo UART is the dedicated GPIO6/GPIO7 bus at `1000000 baud`.
- The BM8563 RTC at I2C `0x51` supplies boot time for WireGuard and is
  refreshed by SNTP or the encrypted native API.
- Serial and USB logging are forbidden. Keep ESPHome logger baud at `0`, keep
  every ESP-IDF console disabled, and observe logs only through the encrypted
  native API over Wi-Fi with `./tools/andy-logs`.
- Do not change bootloader or panic logging.

## Voice and agent behavior

- Production has no wake word. Firmware starts continuous native-API capture
  whenever Andy is connected, awake, and not announcing.
- A neural voice activity detector segments 16 kHz mono PCM into bounded
  utterances. Loudness is measured and decides nothing: the noise that matters
  is louder than the speech it drowns. Empty recogniser results are ordinary
  ambient events, not device errors.
- Every non-empty transcript goes to a conservative calibrated-command router
  or the configured language model. The model chooses `ignore`, `wait`,
  `end_context`, `reply`, `motion`, or explicit `sleep`.
- `ANDY_LLM_API` selects the backend dialect. Azure enforces the decision
  schema and honours `tool_choice`, so the model cannot answer out of format;
  Ollama Cloud supports neither, and the repair and salvage paths carry it.
- `motion` answers from the gate and never reaches the agent's tools, so it is
  only for a request that is a movement and nothing else. A request that also
  asks for anything else is `reply`, and the agent moves by naming a movement
  in its answer. A movement named on any other kind is discarded, never
  performed.
- The gate is told what Andy can do from the objects that are wired, never from
  a fixed paragraph, because it answers for Andy on every turn it does not hand
  to the agent and will otherwise deny abilities he has.
- A completed non-empty newer transcript owns response authority and cancels
  stale reasoning. Raw VAD and empty ASR never cancel pending ASR or reasoning.
- Conversation history is bounded and clears after at least 15 seconds of
  silence. `sleep` is used only for an explicit request to stop listening.
- The microphone must stop and report a successful capture-pause handshake
  before Andy's speaker starts. STT never runs on Andy's own speech.
- Listening, LLM work, and bounded physical motion are independent tasks.
  Motion may continue while a later capture window is open. A replacement
  motion cancels the active program through the emergency-stop path.
- The LLM receives a trusted read-only runtime snapshot. It never supplies a
  servo angle, step, speed, limit, entity name, pose, or choreography.
- Exact calibrated commands use a deterministic route before the LLM. Natural
  requests for 30 degrees right, left, or up map directly to `look_right`,
  `look_left`, or `look_up`. Unsupported angles fail closed and are never
  approximated.

## Motion safety

- Servo ID 1 is yaw and ID 2 is pitch.
- Fixed targets are home `466/620`, left 30° `381/620`, right 30° `552/620`,
  up 30° `466/705`, down 15° `466/577`, diagnostic yaw +10° `495/620`, and
  diagnostic pitch +10° `466/648`, all at speed `300`.
- Safe ranges are yaw `196..737` and pitch `566..828`. Do not widen or
  rederive them.
- Named programs are composed only from fixed poses in
  `server/src/andy/motion.py`. `docs/motion-vocabulary.md` is the interaction
  contract.
- Every pose performs rail settle, torque-off preflight, telemetry checks,
  alternating-axis feedback, tracking verification, verified torque release,
  and rail power-off.
- Every completion, rejection, fault, emergency stop, shutdown, cancellation,
  or API loss must leave both torque bits disabled and the servo rail off.
- A detected hardware fault — failed preflight, torque readback mismatch, unsafe
  target or telemetry, confirmed feedback loss, confirmed stall, or tracking
  error — latches `motion_inhibited`. No further motion starts until the
  `Clear motion inhibit` button is pressed or the server reconnects.
- Emergency stop does not latch `motion_inhibited`. The server presses that
  button to cancel a motion that a newer one supersedes, and latching there
  would block the replacement.
- A non-motion diagnostic action must never actuate a servo.

## Closed-loop release budget

- Run the complete server suite once after a coherent implementation pass.
- Validate the production ESPHome configuration once per pass. Compile only
  when firmware changed.
- Use three to five physical end-to-end cycles at most, counting failures.
  Stop at five and finish with software tests and existing evidence.
- A deployment or a physical trial requires telling the user immediately
  before the deployment, any audible output, and any motion.
- Long endurance soaks are outside the release loop unless the user explicitly
  requests one.

## Host observation rig

Run `./tools/andy-host-check` before any physical trial.

| Function | Stable configuration |
|---|---|
| External camera | Anker PowerConf C200 at `/dev/video0` |
| Video | 1920x1080 MJPEG, 30 fps; evidence encoded at 10 fps |
| Focus | Continuous autofocus off, fixed focus `396` |
| Anti-flicker | 50 Hz (`power_line_frequency=1`) |
| Room microphone | C200 PipeWire source, 48 kHz stereo |
| Test speaker | S32B80P HDMI PipeWire sink |
| Synthetic voice | Kokoro at `192.0.2.20:8880`, voice `af_heart` |
| ASR | `192.0.2.20:8881/transcribe` |
| Production agent | `192.0.2.20:8900` |

The CoreS3 onboard camera is what Andy sees with, not what proves what he did.
Never claim robot-camera evidence. The C200 is the release visual channel.

The HDMI display drops the beginning of a newly active stream. Digital silence
does not wake it. `./tools/andy-play` and `./tools/andy-say` prepend a
three-second 330 Hz warm-up at amplitude `0.25` in the same stream. Do not use
`pw-play` directly for prompts and do not replace the tone with silence.

Tell the user immediately before:

- any audible output from the computer or Andy;
- any physical robot movement;
- any robot reboot or firmware deployment;
- any production server restart.

Relevant commands from the repository root:

```bash
./tools/andy-host-check
./tools/andy-camera-setup
./tools/andy-snapshot
./tools/andy-observe 15
./tools/andy-say "Beginning now: every word of this sentence is audible."
./tools/andy-logs
./tools/andy-firmware-deploy --apply
./tools/andy-server-promote --apply
./tools/andy-release-canary
```

`andy-release-canary` is physical and audible. It records C200 video and room
audio, encrypted Wi-Fi logs, production journal output, API snapshots, and
starts with a reply-only onboard-speech gate. Motion is permitted only after
that reply is intelligible in the room. It then covers look-right, nod, and
dance, requiring three accepted and completed actions, 14 motion starts and
completions, zero faults or voice errors, no speech detection while Andy
announces, final torque `0/0`, rail power-off, and resumed passive listening.
It records each exchange from the C200 microphone, derives a post-stimulus
response clip with a two-second pre-roll, and sends that clip to room ASR. The
response transcripts must contain `four` for the speech gate, then `look` +
`right`, `yes` + `nod`, and `dance` + `time`. An announcement start, `PLAYING`
state, finish counter, HTTP 200, or non-silent waveform is never evidence that
Andy spoke.

The canary produces a 20-frame C200 contact sheet for each command. Its exit
status is necessary but not sufficient for release acceptance: inspect all
three sheets and the response-transcript JSON files before reporting a physical
pass. The sheets must visibly show look-right and return, the vertical nod, the
dance choreography, and the final centered pose.

Correlate all applicable evidence:

1. C200 video proves visible face and motion behavior.
2. C200 room audio proves an onboard reply entered the room only when its
   isolated response transcript contains the command-specific expected words.
3. Encrypted ESPHome API logs prove internal lifecycle, counters, target
   tracking, torque, rail state, reconnects, and faults.
4. Server journal and HTTP snapshots prove ASR/LLM/TTS decisions, action
   authorization, provider health, and final state.

HDMI playback is only a stimulus and cannot prove Andy's onboard speaker.
Visible stillness cannot prove torque or rail state.

## Deployment order

Deploy the AGX WireGuard runtime when it changed, deploy firmware when it
changed, then promote the server:

```bash
./tools/andy-firmware-deploy --apply
./tools/andy-server-promote --apply
curl --fail http://192.0.2.20:8900/health
curl --fail http://192.0.2.20:8900/actions
curl --fail http://192.0.2.20:8900/motions
```

Firmware deployment verifies the exact MAC, device name, and ESPHome project
identity immediately before Wi-Fi OTA and never opens serial. Server promotion
renders the exact production environment locally from `.env`,
`firmware/secrets.yaml`, and the checked-in contract. It transfers only that
mode-`0600` rendered environment, builds an isolated Python 3.12 uv candidate,
atomically restarts production, and restores the preceding production tree if
health, model availability, device identity, or the motion catalog is not
ready.
