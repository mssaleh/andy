# Andy motion vocabulary

## Authority

`../Will-Robot` is authoritative only for this unit's servo offsets,
angle-to-step conversion, measured travel envelope, speed, and feedback-derived
safety limits. Andy's motion names, sequences, natural-language vocabulary, and
agent policy are defined in this repository.

Vendor and community projects supply interaction ideas such as gaze, social
gestures, scanning, celebration, and dance. Their angles, timings, transports,
and safety behavior are not calibration inputs.

## Fixed poses

All targets use `round((angle + offset) * 2.844)`, yaw offset `164`, pitch
offset `173`, and speed `300`.

| Pose | Logical yaw/pitch | Target | Use |
|---|---:|---:|---|
| `home` | 0° / 45° | `466/620` | Center and level |
| `left_30` | -30° / 45° | `381/620` | Visible left gaze |
| `right_30` | +30° / 45° | `552/620` | Visible right gaze |
| `up_30` | 0° / 75° | `466/705` | Visible upward gaze |
| `down_15` | 0° / 30° | `466/577` | Conservative choreography pose |
| `yaw_positive_10` | +10° / 45° | `495/620` | Diagnostic yaw pose |
| `pitch_positive_10` | 0° / 55° | `466/648` | Diagnostic pitch pose |

The downward pose is smaller because measured pitch travel is asymmetric.
Every target remains inside yaw `196..737` and pitch `566..828`.

Each pose independently performs:

1. a 1.5-second rail settle;
2. verified torque-off preflight;
3. starting position, voltage, temperature, current, and load checks;
4. bounded movement with alternating-axis feedback;
5. confirmed-stall and feedback-loss supervision;
6. final tracking verification;
7. verified torque release and rail power-off.

## Named programs

The firmware owns the choreography. Each program is a keyframe table in
`firmware/emotion_profiles.h`, run with the rail energised for the whole
sequence, and every frame still passes the guards above.

| Program | Shape | Duration |
|---|---|---:|
| `home` | return to centre | ~4 s |
| `look_left` / `look_right` / `look_up` | exact calibrated gaze, hold, return | ~4 s |
| `nod_yes` | two deep nods through most of the pitch range | ~5.5 s |
| `shake_no` | four wide, fast yaw beats | ~6.5 s |
| `bow` | down to the bottom of travel, hold, rise | ~4.5 s |
| `greet` | rise, sweep each side, level off | ~6 s |
| `celebrate` | fast diagonals across the corners | ~7.5 s |
| `scan` | slow sweep across the yaw range, pausing at each end | ~8 s |
| `dance` | 24 frames: wide sweeps, corner diagonals, pitch pumps, short beats | ~23 s |
| `yaw_positive_10` / `pitch_positive_10` | diagnostic single pose | ~4 s |

Gaze keeps its exact calibrated targets, because "look right" means thirty
degrees and the release checks that number. Expressive programs work about 80%
of the measured travel on each axis, yaw 252..680 and pitch 572..782, and the
firmware validates every target against 196..737 and 566..828 regardless.

Rhythm comes from mixing amplitudes, not from raising speed. Travel time is what
costs: a 200-step sweep takes 400 ms at any speed the servo allows, so short
beats carry the pulse and wide accents punctuate it. Speed runs 100 to 500
across the range `../Will-Robot` records for this unit.

A pose ends when it arrives rather than when its worst-case deadline expires.
The deadline bounds how long a move may take; waiting it out on every frame is
what made a sequence read as a series of separate movements.

`server/src/andy/motion.py` selects a program and presses once. It does not
assert a frame count, which would only be guessing at the firmware's routine;
it asserts that something moved, that everything which started also completed,
that no fault was raised, and that the device ended in its verified terminal
state with torque released and the rail off.

## Natural-language routing

`server/src/andy/actions.py` has two semantic layers:

1. A conservative deterministic router recognizes exact unambiguous requests
   such as “look right,” “turn your head right by thirty degrees,” “say yes
   with your head,” and “show me a dance.”
2. GLM-5.2 handles incomplete language, pronouns, conversational context,
   background speech, and less literal requests using the complete catalog.

Both layers produce the same `ActionDecision` and pass through the same fixed
allowlist. The deterministic router deliberately does not match a motion phrase
embedded inside unrelated speech.

Requests for exactly 30° left, right, or up map to the corresponding gaze
program without a confirmation question. Unsupported directional angles are
rejected before the model can approximate them. The 10° programs require
explicit diagnostic yaw-positive or pitch-positive language.

Spoken acknowledgements are fixed for deterministic requests and bounded to one
or two sentences for model-selected requests. The LLM never supplies physical
parameters.

## Concurrency and cancellation

A program is dispatched after its response WAV is ready. It can run while Andy
announces and can continue after passive capture resumes. The microphone itself
remains stopped for the complete announcement.

Ordinary conversation does not cancel motion. A new motion request cancels the
active program before starting its replacement. Cancellation during a
dispatched pose presses the firmware emergency-stop button. API disconnect,
shutdown, fault, or timeout also reaches a torque-off, rail-off terminal state.

## Release check

`./tools/andy-release-canary` exercises `look_right`, `nod_yes`, and `dance`.
Those programs cover 14 independently verified pose executions. A passing run
requires three accepted and completed actions, 14 starts, 14 completions, zero
faults, visible matching movement, final torque `0/0`, rail power-off, and
resumed passive listening.

Physical release work is limited to three to five cycles, including failed
cycles.
