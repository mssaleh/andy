#pragma once

#include "esphome/components/scs9009/scs9009.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome::andy_scs9009 {

// The pinned vendor component accepts uint8_t in read_pos(), read_load(), and
// its related accessors, but those methods test for -1 to select the feedback
// cache. That branch is unreachable. This adapter exposes the cache populated
// by one successful feedback() call without issuing extra UART transactions.
class AndySCS9009Component : public scs9009::SCS9009Component {
 public:
  void setup() override {
    scs9009::SCS9009Component::setup();
    // This unit answers read instructions but does not return status packets
    // after writes. Matching that response level prevents a 500 ms timeout
    // after every torque or position command.
    this->level_ = 0;
  }

  int cached_position() const { return this->cached_word_(0); }

  int cached_load() const { return this->decode_signed_(this->cached_word_(4), 10); }

  int cached_voltage() const { return this->mem_[6]; }

  int cached_temperature() const { return this->mem_[7]; }

  int cached_current() const { return this->decode_signed_(this->cached_word_(13), 15); }

  int feedback(uint8_t id) {
    if (!this->read_bounded_(id, SCSCL_PRESENT_POSITION_L, this->mem_,
                             sizeof(this->mem_), 8)) {
      this->error_ = 1;
      return -1;
    }
    this->error_ = 0;
    return sizeof(this->mem_);
  }

  int feedback_verified(uint8_t id) {
    int result = this->feedback(id);
    if (result > 0) {
      return result;
    }
    delay(2);
    result = this->feedback(id);
    if (result > 0) {
      ESP_LOGI("andy.scs9009", "Feedback read for servo %u recovered on attempt 2",
               id);
    }
    return result;
  }

  int read_torque_state(uint8_t id) {
    uint8_t value = 0;
    if (!this->read_byte_bounded_(id, SCSCL_TORQUE_ENABLE, value, 8)) {
      return -1;
    }
    return value;
  }

  // The SCS0009 control specification permits a 1 ms update period. Leave
  // twice that interval between the two addressed writes so the second servo
  // never has to accept a frame at the limit. Torque writes are idempotent.
  void set_torque_pair(uint8_t enabled) {
    this->enable_torque(1, enabled);
    delay(2);
    this->enable_torque(2, enabled);
  }

  // A write carries no acknowledgement on this unit, so read both SRAM torque
  // bits and retry the complete pair once. Callers still cut the servo rail and
  // report a fault if the requested state cannot be verified.
  bool set_torque_pair_verified(uint8_t enabled, int &yaw_state,
                                int &pitch_state) {
    int first_yaw_state = -1;
    int first_pitch_state = -1;
    for (uint8_t attempt = 1; attempt <= 2; attempt++) {
      this->set_torque_pair(enabled);
      delay(2);
      yaw_state = this->read_torque_state(1);
      delay(1);
      pitch_state = this->read_torque_state(2);
      if (attempt == 1) {
        first_yaw_state = yaw_state;
        first_pitch_state = pitch_state;
      }
      if (yaw_state == enabled && pitch_state == enabled) {
        if (attempt > 1) {
          ESP_LOGI("andy.scs9009",
                   "Torque pair readback recovered on attempt %u; requested=%u first=%d/%d final=%d/%d",
                   attempt, enabled, first_yaw_state, first_pitch_state,
                   yaw_state, pitch_state);
        }
        return true;
      }
    }
    return false;
  }

 protected:
  bool read_byte_bounded_(uint8_t id, uint8_t address, uint8_t &value,
                          uint32_t timeout_ms) {
    return this->read_bounded_(id, address, &value, 1, timeout_ms);
  }

  bool read_bounded_(uint8_t id, uint8_t address, uint8_t *data,
                     size_t length, uint32_t timeout_ms) {
    this->r_flush_scs_();
    uint8_t requested_length = static_cast<uint8_t>(length);
    this->write_buffer_(id, address, &requested_length, 1, INST_READ);
    this->w_flush_scs_();

    const uint32_t started_at = millis();
    auto read_one = [&](uint8_t &byte) {
      while (true) {
        if (this->available() > 0 && this->read_array(&byte, 1)) {
          return true;
        }
        if (millis() - started_at > timeout_ms) {
          return false;
        }
        yield();
      }
    };

    uint8_t previous = 0;
    uint8_t current = 0;
    bool header_found = false;
    while (read_one(current)) {
      if (previous == 0xFF && current == 0xFF) {
        header_found = true;
        break;
      }
      previous = current;
    }
    if (!header_found) {
      ESP_LOGD("andy.scs9009",
               "Bounded read failed: id=%u address=%u reason=header-timeout",
               id, address);
      return false;
    }

    // Status packet after the FF FF header: ID, length, error, data, checksum.
    uint8_t fields[3];
    for (uint8_t &byte : fields) {
      if (!read_one(byte)) {
        ESP_LOGD("andy.scs9009",
                 "Bounded read failed: id=%u address=%u reason=fields-timeout",
                 id, address);
        return false;
      }
    }
    if (fields[0] != id || fields[1] != length + 2 || fields[2] != 0) {
      ESP_LOGD("andy.scs9009",
               "Bounded read failed: id=%u address=%u reason=fields value=%u/%u/%u",
               id, address, fields[0], fields[1], fields[2]);
      return false;
    }

    uint8_t sum = fields[0] + fields[1] + fields[2];
    for (size_t index = 0; index < length; index++) {
      if (!read_one(data[index])) {
        ESP_LOGD("andy.scs9009",
                 "Bounded read failed: id=%u address=%u reason=data-timeout index=%u",
                 id, address, static_cast<unsigned>(index));
        return false;
      }
      sum += data[index];
    }
    uint8_t received_checksum = 0;
    if (!read_one(received_checksum)) {
      ESP_LOGD("andy.scs9009",
               "Bounded read failed: id=%u address=%u reason=checksum-timeout",
               id, address);
      return false;
    }
    const uint8_t expected_checksum = static_cast<uint8_t>(~sum);
    if (expected_checksum != received_checksum) {
      ESP_LOGD("andy.scs9009",
               "Bounded read failed: id=%u address=%u reason=checksum expected=%u received=%u",
               id, address, expected_checksum, received_checksum);
      return false;
    }
    this->error_ = 0;
    return true;
  }

  int cached_word_(size_t offset) const {
    return (static_cast<int>(this->mem_[offset]) << 8) |
           static_cast<int>(this->mem_[offset + 1]);
  }

  static int decode_signed_(int value, uint8_t sign_bit) {
    const int sign_mask = 1 << sign_bit;
    return (value & sign_mask) ? -(value & ~sign_mask) : value;
  }
};

}  // namespace esphome::andy_scs9009
