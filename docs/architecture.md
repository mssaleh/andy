# Andy architecture

## Runtime boundary

Andy has one production path:

```text
CoreS3 microphone
  -> ESPHome continuous 16 kHz mono capture
  -> encrypted native API
  -> server neural voice activity detection
  -> speech recognition
  -> deterministic calibrated-command router or GLM-5.2
  -> Kokoro TTS and/or named motion controller
  -> encrypted native API
  -> CoreS3 speaker and fixed servo buttons
```

The HTTP application exposes `/health`, `/actions`, `/motions`, and short-lived
`/tts/{key}.wav` assets. Robot control does not use a second WebSocket or an
unvalidated free-form command endpoint.

## Network topology

Andy is `10.0.0.2` and the AGX production server is `10.0.0.3` on the cloud
WireGuard network. The native API session is sourced from `.3` to `.2:6053`;
the LAN address `192.0.2.10` is reserved for recovery and OTA.

```text
Andy 10.0.0.2 -> WireGuard peer configured in firmware secrets

AGX agent 10.0.0.3 -> cloud WireGuard router -> Andy 10.0.0.2:6053
Andy -> cloud WireGuard router -> AGX 10.0.0.3:8900/tts/{key}.wav
```

Andy has one WireGuard peer and no LAN fallback, so the tunnel behaves the same
on the home network and anywhere else. Response media always uses the AGX
WireGuard address.

Both directions hairpin through the cloud router, which puts a full
wide-area round trip between the server and the robot. Every transport
decision below is sized for that round trip rather than for a LAN.

The firmware's vendored WireGuard receive path coalesces an ESP-NETIF pbuf
chain into one contiguous UDP datagram before authentication and decryption.
Media transport is sized for that round trip. The speaker pipeline banks 48 KiB
of the 24 kHz mono stream before it starts, one second of audio, because a
prebuffer shorter than one round trip cannot survive a single retransmission.
The server flushes each media response header before its body and emits the WAV
in 1 KiB writes, small enough that a tunnel datagram never fragments, but it
does not rate limit them. Playback consumes 48,000 B/s, and pacing anywhere near
that rate starves the speaker the moment the device buffer drains, because a
sleep is a floor and socket drain on a link this long pushes the real interval
past it. TCP is the rate controller and the socket's unsent-data limit is the
backpressure.

## Ownership

| Concern | Owner |
|---|---|
| Shared I2S clocks, ES7210 input, AW88298 output | ESPHome `esp_audio_stack` |
| Continuous capture and capture/playback handshake | ESPHome production firmware |
| Utterance segmentation and silence bounds | Python Silero voice activity detection |
| Recogniser, GLM-5.2, and Kokoro calls | Python provider adapters |
| Looking: one frame, described or searched | Python vision provider |
| Ambient/conversation/agent decision | Python turn coordinator |
| Exact calibrated natural-language fast path | Python action policy |
| Named choreography and completion validation | Python motion controller |
| Fixed targets and physical safety | ESPHome motion subsystem |
| Face state | ESPHome display |
| Showing that the camera was used | ESPHome camera trigger |
| Where Andy is, and where the sun is from there | ESPHome location package |
| Tunnel reachability | ESPHome WireGuard subsystem |
| AGX `.3` WireGuard interface | AGX host |
| Closed-loop external evidence | C200 video/audio plus Wi-Fi telemetry |

## Audio topology

The CoreS3 audio bus runs at 48 kHz under one full-duplex owner. The ES7210
right channel is DC-corrected and converted to 16 kHz mono for capture. No
acoustic echo canceller is in the production stream: the capture/playback
handshake prevents simultaneous microphone capture and Andy speech.

Kokoro returns a 24 kHz WAV. The server accepts uncompressed mono or stereo
PCM16 and normalizes to 24 kHz, which is a passthrough for Kokoro's own output,
and stores a short-lived WAV. The announcement pipeline decodes at 24 kHz and a
resampler speaker converts to the fixed 48 kHz hardware rate.

```text
Kokoro WAV
  -> server PCM16 validation and 24 kHz normalization
  -> bounded in-memory WAV
  -> ESPHome announcement decoder at 24 kHz
  -> resampler speaker to 48 kHz
  -> esp_audio_stack speaker
  -> AW88298
```

Before any announcement, the server presses the encrypted
`pause_capture_for_response` button and waits for the capture-pause counter to
advance. Only then does it submit the media URL. ESPHome resumes continuous
capture after the announcement reaches idle. If announcement startup or
completion is cancelled or times out, the server sends an explicit media stop
so that the device reaches idle and reopens capture.

## Continuous turn management

Production has no wake word. ESPHome repeatedly starts continuous capture while
the API is connected, listening is enabled, and no announcement is active.
Voice activity is judged by Silero, a small neural detector that runs in this
process on 512-sample chunks and costs 0.06 ms each, about a fifth of a percent
of real time. The detector works on a 20 ms frame grid and the model consumes
32 ms chunks, so a frame that completes no chunk carries the verdict of the
last one that did. The bounds are:

| Bound | Value |
|---|---:|
| Speech start evidence | 60 ms in a 100 ms window |
| Minimum voiced audio | 200 ms |
| End silence | 800 ms |
| No-speech window | 10 s |
| Maximum utterance, from speech onset | 15 s |
| Maximum capture window | 30 s |

A spectral detector judges voicing rather than speech, so a keystroke, a chair,
a fan and mains hum all read as a person to it. Loudness cannot rescue that
judgement, because the noise is often the louder of the two: measured on this
rig, 60 Hz hum at RMS 2895 is louder than real speech at RMS 1639, and a
spectral detector calls it speech in 99.6% of frames where the neural one calls
it speech in none. In 45 seconds of an ordinary noisy room -- a television, a
video, people moving -- the spectral detector opened four utterances and the
neural detector opened none, while the neural detector still admitted real
speech at RMS 244, below the level the loudness gate had settled on.

The room level is still measured on every frame, because it is how a capture is
read afterwards, but it no longer decides anything: an AND on loudness can only
discard frames the detector already accepted. `ANDY_VAD_SPEECH_THRESHOLD` sets
how sure the detector must be to start an utterance, and a lower bar holds it
open, so an ordinary dip between words does not end a sentence. Every segment
logs what it measured, in speech probability and in room level.

`ANDY_VAD_ENGINE` selects the detector. The spectral one remains available for
comparison; nothing in production uses it.

Only a short run-up is retained before speech begins. The recogniser receives
that run-up plus the utterance, not the whole window, because transcribing
minutes of room around a moment of speech is what makes it answer `[BLANK_AUDIO]`.

A capture run closes before provider work begins. This lets firmware open a new
capture window while ASR and reasoning proceed:

```text
CAPTURE -> RUN_END -> ASR -> DECIDE -> TTS
    \________________ next capture may begin __/
```

Response authority belongs to whatever is being said, not to whatever was heard
most recently. Every completed transcript receives a monotonically increasing
generation, but a generation takes the floor only once the gate has decided it
will produce speech or movement. Raw speech starts, pending ASR, and transcripts
the gate discards never take it, so nothing that Andy is not going to answer can
cancel an answer already being prepared.

The recogniser labels non-speech audio in brackets -- `[SOUND]`, `[BLANK_AUDIO]`,
`[typing]`, `(water running)`. A transcript that is nothing but such labels is
discarded before the gate runs: it costs no model call and takes no authority.

The gate is told what Andy can actually do, assembled from the objects that are
wired rather than written into the prompt, because the gate answers for Andy on
every turn it does not hand to the agent. Asked to set a reminder while holding
a working scheduler it had answered that it could not, and a list that is built
from the live objects cannot drift from the truth the way a paragraph does.

The decision protocol is one strict JSON object with one of:

- `ignore` for noise or speech not directed to Andy;
- `wait` for an incomplete fragment;
- `end_context` for a naturally completed exchange;
- `reply` for ordinary conversation;
- `motion` with one allowlisted name, when the request is a movement and
  nothing else;
- `sleep` only for an explicit request to stop listening.

A request that asks for a movement *and* something else -- a reminder, a fact to
remember, something to look at -- is `reply`, because `motion` answers from the
gate and never reaches the tools. A movement named on any other kind is
discarded rather than treated as malformed: the agent decides the body on a
reply turn, and rejecting the decision outright spends the one repair round and
then leaves Andy silent, which is a worse failure than an ignored field and the
only one of the two that a listener notices.

Malformed output receives one bounded repair request and then fails closed.
Pending fragments are limited to 1,000 characters. Conversation history is
limited to eight user/assistant pairs and clears after `ANDY_SESSION_IDLE_SECONDS`
of silence, three minutes by default, so an ordinary pause in a conversation does
not discard it. Speech the gate ignores leaves a held fragment untouched, because
the fragment belongs to whoever was mid-sentence. Ambient text is not accumulated
indefinitely.

The face uses green for both `listening` and `speech detected`. In a room whose
noise repeatedly crosses VAD, the face can look continuously green even though
capture generations are closing and restarting normally. Progress is determined
from advancing turn-start and turn-end counters plus zero voice errors, not from
color alone.

## Semantic action boundary

The deterministic router handles only exact, unambiguous calibrated requests,
including natural variants for the release commands. It maps 30 degrees right,
left, and up directly to `look_right`, `look_left`, and `look_up`. A directional
angle outside the calibrated catalog becomes a spoken rejection before the LLM
or motion layer can reinterpret it. Incidental motion words embedded in other
speech remain with GLM-5.2 for semantic classification.

The agent decides Andy's body the way it decides his face: as part of its
answer rather than through a tool. A tool that runs a motion program cannot
return until the program finishes, and the dance is eight poses and eight and a
half seconds, so a model waiting on one is a robot that moves in silence and
speaks afterwards. Named in the answer instead, the movement is dispatched
beside the speech and validated against the same allowlist, so Andy moves while
he talks and an invented name costs a retry rather than reaching the servos.

## Looking

The camera is not polled. A frame crosses the same tunnel as everything else and
costs one to two round trips, so what is cached is the frame rather than the
answer: "what can you see?" and "are my keys there?" are two questions about one
photograph, and taking a second would double the only cost that matters.

Two ways of asking share it. A vision-language model returns a sentence, which
is what someone means by asking what Andy can see. An open-vocabulary detector
running on the AGX answers about named things, locally, in about 80 ms once its
phrases are encoded, and returns nothing at all when the thing is not there --
which is an answer rather than a failure. Its confidence threshold is measured
rather than chosen: below it one monitor is reported six times and cables appear
that do not exist, above it the monitor that is there disappears.

Neither is part of the health gate. A robot that cannot be asked about the keys
is degraded; a robot that cannot be spoken to is broken, and only the second is
worth rolling a release back for.

The robot says so itself. `on_image` fires on the main loop for every frame the
camera delivers, whoever asked for it, and raises a mark in the corner of the
face for two and a half seconds; `camera_in_use` carries the same fact over the
API. The server cannot do this job honestly on its own: it would only cover the
frames it requested, and a camera indicator that depends on one client being
polite is not an indicator.

The redraw is deliberately not done inside that callback. Everything done there
is charged to the camera's own operation window, and redrawing the face from it
measured 268 ms against the component's budget where the motion supervisor runs
every 25 ms. A 250 ms interval brings the screen into line instead, and skips
entirely while a pose is running, which is the rule `light.yaml` already follows
for the ring. Moving the redraw out took the camera's window to 113 ms, which is
the capture and JPEG encode alone.

## What Andy knows about himself

The robot carries a hundred and two entities and the agent used to be told
fourteen facts, none of which was the time. Asked what day it was, it said it
did not know.

The split is by cost, not by category. Facts that describe the situation are in
front of the model on every turn: the date and time, what part of the day it is
and whether it is light outside, who is close, the light level, the mood, the
battery, which way the head is pointing, how long Andy has been awake. Facts
that describe the machine are behind `check_myself`: motor temperature, power
draw, free memory, faults, whether he is upright. Forty numbers on every turn
is forty numbers nobody reads, and someone asking "are you all right?" is the
only person who wants them.

Every fact is named for what its sensor can actually know. The proximity sensor
sits behind the front glass and triggers at about arm's length; handed to the
model as presence, it told a person sitting a metre away that Andy was by
himself. It is `someone_close_to_me` now, and a question about the room is
answered by looking.

The part of the day comes from the sky rather than the clock. Eight in the
evening is light in June and dark in December, so the hour alone gets it wrong
twice a year in opposite directions.

Andy finds his own position rather than being told it. One request returns the
location of the address it arrives on, and his ordinary traffic leaves through
the house rather than the tunnel, so that address is the house's.

It is asked on every boot as soon as there is a network, retried each minute
until that boot has its own answer, and refreshed every three hours. None of
those three is redundant. Boot alone would leave a robot carried to another
city answering for the old one until something restarted it. The three-hour
refresh alone would leave the place name blank for hours after a restart,
because the position survives in flash and the name does not -- so "do I know
where I am" is the wrong question to gate the retry on, and "has this boot
asked" is the right one.

Until it is located there is no position, and nothing pretends otherwise. The
sun component will happily compute for latitude zero -- it published sunrise at
09:59 and sunset at 22:06 here, which is the Gulf of Guinea -- so those
readings are withheld at the source and the server ignores them again. A fact
that looks right is acted on, which makes a confident wrong answer worse than
an absent one. The clock still names the part of the day, because the hour is
always known.

GLM-5.2 receives:

- the conversational system prompt;
- the complete named motion catalog and semantics;
- explicit angle and no-confirmation rules;
- bounded conversation history;
- a trusted read-only action/device snapshot;
- the current combined transcript.

The parser accepts only `MotionAction` enum members. Neither path can produce a
runtime angle, pose target, speed, safety threshold, entity name, button key, or
choreography.

## Parallel work and self-speech exclusion

The coordinator treats capture, response generation, playback, and motion as
separate tasks:

- capture can restart while ASR or GLM-5.2 is working;
- a motion program starts after TTS media is ready and may overlap Andy's
  acknowledgement;
- capture remains stopped for the complete announcement;
- capture can resume while a longer motion program continues;
- ordinary conversation does not cancel a running motion;
- a replacement motion cancels the current program and invokes emergency stop
  if a pose was dispatched;
- disconnect and shutdown cancel provider, playback, and motion work.

This model permits listening, talking, reasoning, and action to make progress
without using microphone audio during Andy's own speech.

## Motion lifecycle

The server serializes named programs. Every program step invokes one fixed
firmware button and waits for a fresh start and completion counter:

```text
IDLE -> RAIL_SETTLE -> TORQUE-OFF PREFLIGHT -> MOVING -> VERIFY -> IDLE
                           |                    |         |
                           +------------------ FAULT -----+
```

Firmware enforces the measured target bounds, speed, voltage, temperature,
current, load, feedback-loss, stall, and deadline rules. The 25 ms scheduler
alternates axes, so each servo is sampled every 50 ms without blocking the
ESPHome main loop.

The server then verifies:

- exactly one start and one completion increment per pose;
- no motion-fault increment;
- the exact expected target pair;
- no more than 14 steps of yaw or pitch error;
- final torque `0/0`.

Every terminal path releases torque and switches off the servo rail. An API
disconnect also triggers the firmware emergency-stop button.

## Invariants

- Production capture is passive and has no wake word.
- STT never processes Andy's own speech.
- Empty ASR and unrelated speech are normal ambient events.
- New response authority belongs only to a completed non-empty transcript.
- Provider timeouts, malformed model output, and disconnects fail closed.
- The LLM cannot create physical parameters or bypass the motion allowlist.
- Unsupported angles are never approximated.
- TTS media is bounded, short-lived PCM16 at 48 kHz.
- Motion completion always includes target, counter, fault, tracking, torque,
  and rail verification.
- Serial logging remains disabled; device observation uses encrypted Wi-Fi.
- The onboard camera is requested, never streamed, and one frame answers every
  question asked about that moment.
- A frame never leaves the robot without the robot showing it. The mark is
  raised by the camera's own delivery callback, so it covers every client, not
  only the ones that remember to announce themselves.
- Voice activity is judged by a neural detector; loudness is measured and
  decides nothing.
- The gate is told what Andy can do from what is wired, and never answers for
  an ability it holds.
- A movement named on a non-motion decision is discarded, never performed.
- Andy's own camera is not release evidence: it cannot show what Andy did.
