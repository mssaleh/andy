# StackChan hardware contract

## Identity

- Product: M5Stack StackChan K151 with CoreS3 controller.
- Flash: 16 MB.
- PSRAM: 8 MB, quad mode.
- Robot Wi-Fi MAC: `AA:BB:CC:DD:EE:FF`.
- LAN recovery and OTA address: `192.0.2.10`.
- WireGuard production address: `10.0.0.2`.
- Production server WireGuard address: `10.0.0.3`.

The MAC address is checked before any flash. The ESPHome logger has a zero baud
rate and ESP-IDF has no primary or secondary console. Logs and OTA use the
encrypted native API over Wi-Fi because opening the USB serial path resets this
CoreS3.

The logger runs at `INFO`. Every line it emits crosses the WireGuard tunnel, and
anything above the configured level is compiled out rather than filtered, so the
level is a flash and bandwidth decision as much as a readability one: `INFO`
costs 26 KB less flash than `DEBUG` and removes about 187 lines per 50 seconds
from the tunnel. Nothing this project writes logs below `INFO`. Raise it to
`CONFIG` when the boot-time component inventory is needed.

## Buses and pins

| Function | Pins / address |
|---|---|
| Internal I2C | SCL GPIO11, SDA GPIO12, 100 kHz shared bus |
| Servo UART | TX GPIO6, RX GPIO7, 1,000,000 baud |
| I2S MCLK | GPIO0 |
| I2S LRCLK | GPIO33 |
| I2S BCLK | GPIO34 |
| I2S microphone data | GPIO14 |
| I2S speaker data | GPIO13 |
| GC0308 camera clock | GPIO2 |
| GC0308 camera sync / reference / pixel clock | GPIO46 / GPIO38 / GPIO45 |
| GC0308 camera data | GPIO39, GPIO40, GPIO41, GPIO42, GPIO15, GPIO16, GPIO48, GPIO47 |
| IR transmitter / receiver | GPIO5 / GPIO10 |
| PY32L020 expander | I2C `0x6F`; IO1 servo rail, IO14 LED strip |
| BM8563 RTC | I2C `0x51`; WireGuard boot-time clock |
| ES7210 microphone codec | I2C `0x40` |
| AW88298 amplifier | I2C `0x36` after reset release |
| AW9523B expander | I2C `0x58`; interrupt GPIO21 |
| LTR-553ALS light / proximity | I2C `0x23` |
| INA226 body power monitor | I2C `0x41` |
| Si12T head touch | I2C `0x68` |
| BMI270 inertial sensor | I2C `0x69` |
| FT6336U touchscreen | I2C `0x38` |
| ST25R3916 NFC | I2C `0x50`; no ESPHome component exists |

## Expander pin map

AW9523B pins are numbered `P0_x = x` and `P1_x = 8 + x`.

| Pin | Line | Direction |
|---:|---|---|
| 0 | FT6336U reset | output |
| 1 | `BUS_OUT_EN` | output, held on |
| 2 | AW88298 reset | output, held on |
| 3 | ES7210 interrupt | input |
| 4 | microSD card detect | input |
| 5 | `USB_OTG_EN` | output, off |
| 8 | GC0308 reset | output |
| 9 | ILI9342C reset | output |
| 10 | FT6336U interrupt | input |
| 11 | AW88298 interrupt | input |
| 15 | `BOOST_EN` | output, held on |

PY32L020 pins are exposed by their index: pin `0` is IO1 and pin `13` is IO14.

| Pin | Line |
|---:|---|
| 0 | servo `VM_EN` rail |
| 13 | WS2812C strip enable |

## Power and reset

- PY32 pin `0` controls the servo `VM_EN` rail and rests off.
- AW9523B P0 uses push-pull drive.
- AW9523B P0_2 releases the AW88298 reset.
- The amplifier receives at least 50 ms of settle time after reset release.
- AW9523B P1_7 is `BOOST_EN`, the CoreS3 5 V boost converter, and P0_1 is
  `BUS_OUT_EN`. Both are held on because the body's 12-LED strip draws from the
  BUS rail. The AW88298 and the 1 W speaker do not depend on either.
- The AW9523B interrupt on GPIO21 keeps the expander's loop disabled until an
  input changes, so the four input sensors cost no steady-state I2C traffic.

## Main-loop budget

`motion.yaml` supervises an active pose every 25 ms and performs a blocking
servo UART transaction per tick, so main-loop time is a safety property, not a
performance one. `runtime_stats` in `board.yaml` reports per-component cost over
the encrypted API. Measured on this unit:

| Component | Calls | Average | Maximum |
|---|---|---:|---:|
| `esp_audio_stack.microphone` | per loop while capturing | 0.33 ms | 106 ms |
| `voice_assistant` | per loop | 2.1 ms | 102 ms |
| `api` | per loop | 0.13 ms | 77 ms |
| `ltr_als_ps.sensor` | per loop | 0.50 ms | 17 ms |
| `light` (status ring) | per colour change | 33.8 ms | 36 ms |
| `light` (LCD backlight) | per change | 1.9 ms | 1.9 ms |
| `remote_receiver` | per loop | 0.004 ms | 0.7 ms |
| `axp2101.sensor`, `ina226.sensor`, `gpio.binary_sensor` | per loop or per update | ≤0.03 ms | ≤6.8 ms |

Whole-loop peaks of 110–120 ms come from the audio and API path and are present
whenever capture is running. Stopping continuous capture drops the peak to about
56 ms.

Two costs constrain configuration:

- The status ring pays an unconditional `delay(30)` inside the pinned vendor
  `m5ioe1` component's `write_led_ram_`. A continuously-animating effect
  therefore costs about 34 ms per frame; `addressable_rainbow` measured 346
  frames in 30 seconds, 39% of wall-clock. Only a discrete slow effect is
  offered, the ring repaints solely when its resolved colour changes, and it
  never repaints while `motion_active` is true.
- `ltr_als_ps` polls proximity from `loop()` on every iteration whenever `PS` is
  enabled, with no configuration to slow it. Proximity is the only presence
  signal without the camera, so the 0.5 ms per loop is accepted.

## Servo safety

The non-motion diagnostic images never actuate either servo. The combined image
accepts only explicit fixed movement buttons, and the server exposes those
buttons only through its named allowlist. Servo IDs, calibration, and limits
are fixed for this physical unit:

| Axis | ID | Angle conversion | Home | +10° target | Safe steps |
|---|---:|---|---:|---:|---:|
| Yaw | 1 | `round((angle + 164) * 2.844)` | 466 | 495 | 196–737 |
| Pitch | 2 | `round((angle + 173) * 2.844)` | 620 at 45° | 648 | 566–828 |

- Command speed is 100 to 500 and target tolerance is 14 steps. Named poses
  use 300; motion idioms pick per keyframe and intensity scales within range.
- The servo rail settles for 1.5 seconds before any UART transaction.
- Valid voltage is 4.0–7.4 V; temperature is below 60 °C; absolute current is
  below 350; absolute load is below 650.
- The 25 ms supervisor samples alternating axes, so each axis is read every
  50 ms.
- Stall evaluation applies only when target delta is at least 8 steps. It uses
  a stuck delta of at most 1 step plus current rise 80 or absolute current 350,
  or load rise 150 or absolute load 650, and requires two confirmations.
- Two consecutive feedback losses fault the active axis; any valid read resets
  that axis's miss counter.
- Completion, rejection, fault, emergency stop, shutdown, and API loss leave
  both torque bits disabled and the servo rail off.

The pitch axis must never be commanded outside its measured range or driven
into a mechanical stop.
