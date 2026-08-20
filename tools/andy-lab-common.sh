#!/usr/bin/env bash
# Shared, repository-local defaults for Andy's host observation rig.

ANDY_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ANDY_PROJECT_ROOT

# Real addresses for this installation live in an untracked tools/site.env.
# The defaults below are RFC 5737 documentation addresses: they are deliberately
# unroutable, so a missing site file fails visibly instead of reaching a
# stranger's host.
if [[ -f "${BASH_SOURCE[0]%/*}/site.env" ]]; then
  # shellcheck disable=SC1091
  source "${BASH_SOURCE[0]%/*}/site.env"
fi

: "${ANDY_DEVICE_HOST:=192.0.2.10}"
: "${ANDY_DEVICE_MAC:=AA:BB:CC:DD:EE:FF}"
: "${ANDY_FIRMWARE_CONFIG:=${ANDY_PROJECT_ROOT}/firmware/andy.yaml}"

: "${ANDY_CAMERA_DEVICE:=/dev/video0}"
: "${ANDY_CAMERA_FOCUS:=396}"
: "${ANDY_CAMERA_POWER_LINE_FREQUENCY:=1}"
: "${ANDY_CAMERA_AUDIO_SOURCE:=alsa_input.usb-Anker_PowerConf_C200_Anker_PowerConf_C200_SERIALNUMBER-02.analog-stereo}"
: "${ANDY_CAMERA_VIDEO_SIZE:=1920x1080}"
: "${ANDY_CAMERA_FRAME_RATE:=30}"
: "${ANDY_CAMERA_SETTLE_SECONDS:=2}"

: "${ANDY_AUDIO_SINK:=alsa_output.pci-0000_01_00.1.hdmi-stereo}"
: "${ANDY_AUDIO_WARMUP_SECONDS:=3}"
: "${ANDY_AUDIO_WARMUP_FREQUENCY:=330}"
: "${ANDY_AUDIO_WARMUP_VOLUME:=0.25}"
: "${ANDY_AUDIO_POST_WARMUP_MILLISECONDS:=0}"
: "${ANDY_PLAYBACK_GAIN:=1.0}"

: "${ANDY_TTS_URL:=http://192.0.2.20:8880}"
: "${ANDY_TTS_VOICE:=af_heart}"
: "${ANDY_TTS_PLAYBACK_GAIN:=1.4}"
: "${ANDY_ASR_URL:=http://192.0.2.20:8881}"
: "${ANDY_DIAGNOSTIC_SSH_HOST:=192.0.2.20}"
: "${ANDY_VOICE_SERVER_URL:=http://192.0.2.20:8900}"
: "${ANDY_VOICE_SERVER_SERVICE:=andy-server.service}"
# Long enough for a whole exchange: two seconds of pre-roll, the three-second
# HDMI warm-up, the spoken prompt, server reasoning, and a multi-sentence reply,
# which measured about nineteen seconds. A window that ends while Andy is still
# speaking looks exactly like a robot that never answered.
: "${ANDY_TRIAL_DURATION:=45}"

andy_require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    return 1
  fi
}

andy_require_decimal() {
  local value_name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    printf '%s must be a non-negative decimal, got: %s\n' "$value_name" "$value" >&2
    return 1
  fi
}

andy_require_positive_decimal() {
  local value_name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^(0*[1-9][0-9]*)([.][0-9]+)?$ \
    && ! "$value" =~ ^0*[.][0-9]*[1-9][0-9]*$ ]]; then
    printf '%s must be a positive decimal, got: %s\n' "$value_name" "$value" >&2
    return 1
  fi
}

andy_require_unit_decimal() {
  local value_name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^0([.][0-9]+)?$ && ! "$value" =~ ^1([.]0+)?$ ]]; then
    printf '%s must be a decimal from 0 through 1, got: %s\n' \
      "$value_name" "$value" >&2
    return 1
  fi
}

andy_pipewire_has_node() {
  local node_name="$1"
  local media_class="$2"
  pw-dump | jq -e \
    --arg node_name "$node_name" \
    --arg media_class "$media_class" \
    'any(.[];
      .type == "PipeWire:Interface:Node"
      and .info.props["node.name"] == $node_name
      and .info.props["media.class"] == $media_class
    )' \
    >/dev/null
}
