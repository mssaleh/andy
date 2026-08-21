# Andy tools

This directory contains the complete supported command surface for developing,
deploying, observing, and validating Andy. Run commands from the repository
root. Generated Python bytecode and caches are not part of this directory's
source surface.

## Safety contract

- Python is 3.12 and runs only through `./tools/uv` with `--project server` or
  `--project firmware`. `./tools/esphome` delegates to that wrapper.
- Device logs use the encrypted ESPHome native API over Wi-Fi. No tool opens a
  serial or USB console.
- Tell the user immediately before computer or robot audio, robot motion, a
  robot reboot or firmware deployment, or a production server restart.
- Run `./tools/andy-host-check` immediately before any audible or physical
  trial.
- A deployment or physical trial is announced to the user immediately before
  it runs.
- The WireGuard deployment tool changes only the authorized AGX-Orin runtime.
  It never connects to or changes the cloud router.
- Preserve ignored secret sources such as `.env`, `firmware/secrets.yaml`, and
  deployment environment files. Never print their values.
- Default recordings, snapshots, synthesized prompts, and evidence go under
  `/tmp`. Output arguments refuse to overwrite an existing path.

## Environment and firmware

| Tool | Purpose | Effects |
|---|---|---|
| `uv` | Runs uv with managed Python and cache roots inside this repository. Always pass `--project server` or `--project firmware`. | Creates only repository-local Python environments and caches. |
| `esphome` | Runs the pinned ESPHome project through `uv` with repository-local ESPHome and PlatformIO state. | Configuration and compilation are local; an explicit ESPHome upload operation can deploy firmware. |
| `device_info.py` | Internal encrypted-native-API identity and state inspector used by firmware deployment. | Read-only network access to Andy; invoke only through `./tools/uv run --project server --python 3.12`. |
| `andy-firmware-deploy` | Compiles `firmware/andy.yaml`, verifies Andy's MAC, device name, and ESPHome project, then uploads over Wi-Fi. Usage: `./tools/andy-firmware-deploy --apply`. | Deploys firmware and reboots the robot; never uses serial. |
| `andy-logs` | Streams encrypted ESPHome logs for the production firmware or an explicitly supplied firmware YAML. | Read-only network session that runs until interrupted. |

Typical non-deploying checks are:

```bash
./tools/uv sync --project server --python 3.12 --extra dev
./tools/uv run --project server --python 3.12 --extra dev pytest -q
./tools/esphome config firmware/andy.yaml
```

## Host observation

| Tool | Purpose | Effects |
|---|---|---|
| `andy-lab-common.sh` | Internal shared defaults and validation helpers for the C200, HDMI, TTS, device, and AGX endpoints. | Sourced by other shell tools; do not execute it directly. |
| `andy-camera-setup` | Applies C200 fixed focus `396` and 50 Hz anti-flicker, then reads the controls back. | Changes only the established C200 controls on this computer. |
| `andy-host-check` | Verifies required host utilities, C200 video and microphone, HDMI sink, TTS health, and camera controls. | Applies the stable camera controls; produces no sound or robot motion. |
| `andy-snapshot` | Captures one settled C200 frame. Usage: `./tools/andy-snapshot [output.jpg]`. | Reads the camera and writes one image, under `/tmp` by default. |
| `andy-observe` | Records C200 MJPEG video and room microphone audio. Usage: `./tools/andy-observe [seconds] [output.mkv]`. | Reads the camera and microphone and writes one Matroska recording, under `/tmp` by default. |
| `andy-room-audio-check` | Transcribes an existing room-audio artifact and requires every supplied `--expect-word` as a complete normalized word. Usage: `./tools/andy-room-audio-check --input AUDIO [--output NEW_JSON] --expect-word WORD [...]`. Rejects clips of 30 seconds or more. | Read-only ASR call; produces no sound or motion. A mismatch writes evidence JSON and exits nonzero. |

## Audible and physical trials

| Tool | Purpose | Effects |
|---|---|---|
| `andy-play` | Plays an existing non-empty audio file through the fixed HDMI sink with the calibrated three-second 330 Hz warm-up in the same stream. | Audible computer output. |
| `andy-say` | Synthesizes text with Kokoro `af_heart` and delegates playback to `andy-play`. | Audible computer output that Andy may hear. |
| `andy-trial` | Runs the mandatory host check, records C200 video, room audio, and Wi-Fi logs, then speaks one supplied prompt. Records for `ANDY_TRIAL_DURATION`, 45 seconds by default, which covers a multi-sentence reply. Override with `--duration`. | Audible output; the prompt may cause Andy to speak or move. |
| `andy-release-canary` | Runs a reply-only onboard-speech gate, then the single release profile covering look-right, nod, and dance only after that gate passes. It correlates C200, semantic room-audio, device-log, server-log, and HTTP evidence and creates isolated response checks and visual contact sheets. | Audible output; after the speech gate passes, 14 bounded pose executions. |
| `andy-agent-motion-soak` | Internal engine used by `andy-release-canary`; direct use requires an explicit `--profile diagnostic` or `--profile release`. Diagnostic use is bounded to one through five cycles, and the release profile to one cycle. | Audible output and robot motion; requires renewed explicit authorization. |

The room ASR window is 30 seconds and the endpoint does not chunk: a
29-second clip transcribes and a 30-second clip returns an empty string. Record
for as long as the exchange needs, then slice the response window before running
`andy-room-audio-check`, which now rejects an over-long clip rather than
reporting a missing word. Judge audio quality on a multi-sentence reply: a
single word, or a first announcement straight after a reboot, exercises only the
device prebuffer.

`andy-play` and `andy-say` are the only supported HDMI stimulus paths. Do not
call `pw-play` directly because a newly active HDMI stream drops its beginning.
The release canary is the only production release motion sequence; generic
trials collect evidence but do not declare a release pass. A zero canary exit
requires all machine gates, including intelligible onboard replies, but the
three generated visual contact sheets still require explicit inspection before
release acceptance. An early failure stops further stimulation and preserves a
best-effort final state, server journal, observation probe, and `failure.txt`.

## Overrides

Observation defaults live in `andy-lab-common.sh`. Supported overrides include
`ANDY_DEVICE_HOST`, `ANDY_DEVICE_MAC`, `ANDY_FIRMWARE_CONFIG`,
`ANDY_CAMERA_DEVICE`, `ANDY_CAMERA_FOCUS`, `ANDY_CAMERA_AUDIO_SOURCE`,
`ANDY_AUDIO_SINK`, `ANDY_TTS_URL`, `ANDY_TTS_VOICE`, `ANDY_ASR_URL`,
`ANDY_DIAGNOSTIC_SSH_HOST`, `ANDY_VOICE_SERVER_URL`, and
`ANDY_VOICE_SERVER_SERVICE`. Root `.env` is the server operator overlay and
must supply `ANDY_LLM_API_KEY`; the native-API key comes from
`firmware/secrets.yaml`. Deployment-specific environment contracts are in
`server/deploy/production.env.example`.
