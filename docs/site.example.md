# Your deployment

Copy this to `docs/site.md` and fill in your own values. That file is untracked,
because everything in it identifies one robot on one network.

The addresses below are RFC 5737 documentation ranges. They are deliberately
unroutable, so an unconfigured checkout fails visibly rather than reaching a
stranger's host.

## Robot

| | |
|---|---|
| Wi-Fi MAC | `AA:BB:CC:DD:EE:FF` |
| LAN recovery and OTA address | `192.0.2.10` |
| WireGuard address | `10.0.0.2` |
| ESPHome device name | `andy` |
| ESPHome project | `andy.voice-agent` |

## Server

| | |
|---|---|
| LAN address | `192.0.2.20` |
| WireGuard address | `10.0.0.3` |
| Agent HTTP | `192.0.2.20:8900` |
| Robot-facing media base | `http://10.0.0.3:8900` |
| Kokoro TTS | `192.0.2.20:8880` |
| Whisper ASR | `192.0.2.20:8881` |
| Deployment user and home | `youruser`, `/home/youruser` |
| Production tree | `/home/youruser/andy/andy-server-production` |
| Durable state | `/home/youruser/andy/state` |

## Observation rig

| | |
|---|---|
| Camera | Anker PowerConf C200 at `/dev/video0` |
| Room microphone | `alsa_input.usb-Anker_PowerConf_C200_Anker_PowerConf_C200_SERIALNUMBER-02.analog-stereo` |
| Stimulus speaker sink | `alsa_output.pci-0000_01_00.1.hdmi-stereo` |
| Displays | two DisplayPort outputs on `card1`; audio arrives only while a link is up |

## Local environment

`tools/site.env` carries these for the shell tools and is untracked. Copy
`tools/site.env.example` and fill it in; `tools/andy-lab-common.sh` sources it
when present.
