# Host observation rig

## Evidence boundary

The host rig provides synchronized external evidence for Andy:

- the Anker PowerConf C200 records the face, head, base, and room;
- the C200 microphone records HDMI prompts and Andy's onboard speaker;
- the S32B80P HDMI sink supplies synthetic spoken stimuli;
- encrypted ESPHome API logs record internal firmware state;
- production HTTP snapshots and the systemd journal record server state.

The CoreS3 onboard GC0308 camera is configured and is how Andy looks at the
room. It is not an evidence channel: a camera carried by the robot cannot show
what the robot did.

Observation tools do not open USB serial. Camera and audio capture do not issue
motion commands. A command is physical only when its documentation explicitly
says so.

## Stable host configuration

| Item | Value |
|---|---|
| Robot | recovery/OTA `192.0.2.10`, production VPN `10.0.0.2`, MAC `AA:BB:CC:DD:EE:FF` |
| C200 video | `/dev/video0`, 1920x1080 MJPEG at 30 fps |
| Evidence video rate | H.264 at 10 fps |
| C200 focus | autofocus off, manual `396` |
| C200 anti-flicker | 50 Hz |
| C200 room audio | 48 kHz stereo PipeWire source |
| Room ASR window | 30 seconds, unchunked; slice longer recordings |

## When the HDMI sink is missing

`andy-host-check` fails with `HDMI sink is unavailable` when the monitor is
asleep, and no other sink substitutes: the USB outputs are not connected to
anything audible in the room, so `andy-say` plays into silence and Andy's
microphone records only ambient noise at roughly 250 rms.

The sink is absent rather than idle because the display link is down. Confirm it
before hunting anywhere else:

```bash
cat /sys/class/drm/card1-DP-*/status   # connected
cat /sys/class/drm/card1-DP-*/enabled  # disabled when the link is down
grep -l "eld_valid	1" /proc/asound/card2/eld#*   # nothing while it is down
```

`connected` with `enabled=disabled` and no valid ELD means the monitor is
plugged in but the GPU is not driving it. PipeWire cannot create
`alsa_output.pci-0000_01_00.1.hdmi-stereo` without a live link, so the sink
appears only once the display is awake. Wake the monitor, then rerun
`./tools/andy-host-check`.
| HDMI sink | `alsa_output.pci-0000_01_00.1.hdmi-stereo` |
| Kokoro | `http://192.0.2.20:8880`, voice `af_heart` |
| Room ASR | `http://192.0.2.20:8881/transcribe` |
| Production agent | HTTP `192.0.2.20:8900`, WireGuard `10.0.0.3` |

The stable C200 microphone source is
`alsa_input.usb-Anker_PowerConf_C200_Anker_PowerConf_C200_SERIALNUMBER-02.analog-stereo`.
Scripts select stable PipeWire names rather than session node numbers.

Run `./tools/andy-host-check` immediately before a physical test. If the HDMI
sink is missing, wake or enable the display and rerun the check. Never reroute a
test prompt to another speaker automatically.

## HDMI warm-up

The HDMI display loses the first part of a newly active stream. A valid prompt
therefore uses one continuous 48 kHz stereo stream containing:

1. a three-second 330 Hz tone at amplitude `0.25`;
2. the synthesized speech immediately afterward.

Digital silence does not activate the path. `./tools/andy-play` implements this
envelope for an existing WAV. `./tools/andy-say` synthesizes with Kokoro and
delegates to `andy-play`. Do not call `pw-play` directly for a test prompt.

The warm-up is only for the computer's HDMI stimulus. Andy's onboard speaker
does not use it.

## Non-physical observation commands

```bash
./tools/andy-host-check
./tools/andy-camera-setup
./tools/andy-snapshot
./tools/andy-snapshot /tmp/andy-before.jpg
./tools/andy-observe 15
./tools/andy-observe 30 /tmp/andy-observation.mkv
./tools/andy-logs
curl --fail http://192.0.2.20:8900/health
curl --fail http://192.0.2.20:8900/actions
curl --fail http://192.0.2.20:8900/motions
```

`andy-camera-setup` applies fixed focus and anti-flicker. `andy-observe` records
C200 video and lossless FLAC room audio in one Matroska file. `andy-logs` uses
the encrypted native API over Wi-Fi.

## Audible and physical commands

Tell the user immediately before running any command that produces computer or
robot sound:

```bash
./tools/andy-play /tmp/prompt.wav
./tools/andy-say "Beginning now: every word of this sentence is audible."
./tools/andy-trial --duration 15 "What color is the sky?"
./tools/andy-release-canary
```

Tell the user immediately before `andy-release-canary` because it also moves
the robot. Tell the user before any other explicit motion command, robot reboot,
firmware deployment, or production server restart.

## Production release canary

`./tools/andy-release-canary` is a single three-command passive-listening trial:

1. “Please turn your head to the right by thirty degrees.”
2. “Please say yes with your head.”
3. “Please show me a dance.”

The exact phrases resolve through the deterministic calibrated-command router.
The programs cover 2 + 4 + 8 = 14 fixed poses. The collector uses a 90-second
per-command bound so the dance and its safe per-pose checks can finish.

Before stimulation it requires:

- server `0.5.0` health with the recogniser, TTS, GLM-5.2, device, and motion
  ready;
- the exact 13-program motion catalog;
- connected and ready encrypted device transport;
- inactive, uninhibited motion and zero current voice errors.

It records:

- `observation.mkv` with C200 video and room audio;
- `observation-probe.json` with enforced codec, dimensions, frame rate, sample
  rate, channel count, and duration;
- `before.jpg` and `after.jpg`;
- one `exchange-*.wav` beginning before each HDMI prompt;
- one `response-*.wav` derived with a two-second pre-roll at the end of HDMI
  playback, plus its semantic `response-*.json` ASR result;
- one 20-frame `visual-*.jpg` contact sheet for each command interval;
- `timeline.tsv` mapping command intervals into `observation.mkv`;
- `device.log` from Wi-Fi only;
- `server.log` from the production journal;
- `server-health.json` and `motion-catalog.json`;
- before, per-attempt, and final `/actions` snapshots;
- exact Kokoro prompt WAVs;
- a machine-readable attempt table and summary.

An early timeout or interrupted gate stops further stimulation, finalizes the
active recordings, and makes a best-effort capture of final `/actions`, the
server journal, and observation metadata. `failure.txt` names the failed gate;
a successful run does not create that file.

A passing result requires:

- three action requests and three verified completions;
- exactly 14 motion starts and 14 completions;
- zero action failures, rejections, motion faults, voice errors, unexpected
  firmware warnings, API disconnects, and server errors;
- one capture pause, announcement start, and announcement finish per response;
- three speaker `PLAYING` and three speaker `IDLE` states;
- room ASR to find `look` and `right` in the first response, `yes` and `nod`
  in the second, and `dance` and `time` in the third;
- no speech detection between each announcement start and finish;
- an H.264 1920x1080 10 fps observation stream and a 48 kHz stereo FLAC room
  stream;
- three non-empty contact sheets;
- a non-empty server journal with at least three accepted ASR segments and
  exact deterministic-decision, response-synthesis, action-acceptance, and
  action-completion counts;
- every final pose report to contain torque `0/0`;
- motion inactive, passive listening resumed, and the servo rail off.

The canary exits nonzero when any machine gate fails. An exit code of zero is
not by itself release acceptance. Inspect `visual-1-right.jpg`,
`visual-2-nod.jpg`, and `visual-3-dance.jpg` and confirm the commanded
choreography and final centered pose. Inspect the three `response-*.json` files
and confirm `passed: true`; the checker stores the exact transcript, normalized
transcript, expected words, source format, duration, and measured room level.

These signals cannot substitute for one another:

- speaker `PLAYING`, announcement finish, and HTTP 200 prove lifecycle only;
- waveform energy may be a motor, room noise, or music and cannot prove speech;
- HDMI prompt audio cannot prove Andy's onboard speaker;
- visible movement cannot prove the requested pose, released torque, or rail
  power state.

A release pass may use at most three to five physical cycles, including failed
cycles.

## Reviewing existing evidence

The canary runs `ffprobe`, creates the contact sheets, and transcribes the
response clips automatically. Do not play the audio merely to inspect motion.
For an independently captured clip, run:

```bash
./tools/andy-room-audio-check \
  --input /tmp/andy-response.wav \
  --output /tmp/andy-response.json \
  --expect-word look \
  --expect-word right
```

Correlate the evidence by wall-clock time:

1. Video establishes externally visible pose and display changes.
2. Room audio plus a command-specific semantic match establishes that Andy's
   expected response entered the room.
3. Wi-Fi logs establish target, counter, tracking, torque, rail, and fault
   state.
4. Server journal and HTTP snapshots establish transcript, decision,
   authorization, completion, and provider state.

One channel cannot substitute for another. A green face does not prove usable
ASR text. A completion counter does not by itself prove the expected visible
choreography.

Production deliberately renders both `listening` and `speech detected` in
green. If the room repeatedly triggers VAD and ASR returns empty text, that face
may appear continuous. Confirm forward progress with increasing turn-start and
turn-end counters and zero voice errors. Treat it as stuck only when the bounded
capture lifecycle stops advancing or reports an error.

## Overrides

`tools/andy-lab-common.sh` owns checked-in defaults. Relevant overrides include
`ANDY_DEVICE_HOST`, `ANDY_FIRMWARE_CONFIG`, `ANDY_CAMERA_DEVICE`,
`ANDY_CAMERA_AUDIO_SOURCE`, `ANDY_AUDIO_SINK`, `ANDY_TTS_URL`,
`ANDY_TTS_VOICE`, `ANDY_ASR_URL`, `ANDY_DIAGNOSTIC_SSH_HOST`,
`ANDY_VOICE_SERVER_URL`, and `ANDY_VOICE_SERVER_SERVICE`.
