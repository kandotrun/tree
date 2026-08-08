#include "watering_controller.h"

#include <algorithm>
#include <cstring>

namespace watering {

const char* state_name(State state) {
  switch (state) {
    case State::BootGuard:
      return "BOOT_GUARD";
    case State::Idle:
      return "IDLE";
    case State::Watering:
      return "WATERING";
    case State::Cooldown:
      return "COOLDOWN";
    case State::Error:
      return "ERROR";
  }
  return "ERROR";
}

WateringController::WateringController(const ControllerConfig& config,
                                       uint32_t boot_started_at,
                                       const char* restored_request_id)
    : config_(config),
      state_(State::BootGuard),
      state_started_at_(boot_started_at),
      watering_started_at_(boot_started_at),
      active_duration_ms_(config.dose_ms),
      last_runtime_ms_(0U) {
  if (!valid_config()) {
    state_ = State::Error;
    error_reason_ = "INVALID_CONFIG";
    return;
  }
  if (valid_request_id(restored_request_id)) {
    last_request_id_ = restored_request_id;
    remember_request(restored_request_id);
  }
}

bool WateringController::valid_config() const {
  return config_.dose_ms > 0U && config_.dose_ms <= kAbsoluteMaxRunMs &&
         config_.max_run_ms > 0U && config_.max_run_ms <= kAbsoluteMaxRunMs &&
         config_.boot_guard_ms > 0U;
}

bool WateringController::valid_request_id(const char* request_id) {
  if (request_id == nullptr || request_id[0] == '\0') {
    return false;
  }
  std::size_t length = 0U;
  for (const char* cursor = request_id; *cursor != '\0'; ++cursor) {
    ++length;
    if (length > 64U) {
      return false;
    }
    const char character = *cursor;
    const bool allowed =
        (character >= 'A' && character <= 'Z') ||
        (character >= 'a' && character <= 'z') ||
        (character >= '0' && character <= '9') || character == '_' ||
        character == '-';
    if (!allowed) {
      return false;
    }
  }
  return true;
}

bool WateringController::is_duplicate(const char* request_id) const {
  for (std::size_t index = 0U; index < recent_request_size_; ++index) {
    if (recent_request_ids_[index] == request_id) {
      return true;
    }
  }
  return false;
}

void WateringController::remember_request(const char* request_id) {
  recent_request_ids_[recent_request_next_] = request_id;
  recent_request_next_ = (recent_request_next_ + 1U) % kRecentRequestCount;
  recent_request_size_ =
      std::min(recent_request_size_ + 1U, kRecentRequestCount);
}

uint32_t WateringController::scheduled_ms() const {
  return std::min(active_duration_ms_, config_.max_run_ms);
}

uint32_t WateringController::remaining_ms(uint32_t now) const {
  uint32_t duration = 0U;
  switch (state_) {
    case State::BootGuard:
      duration = config_.boot_guard_ms;
      break;
    case State::Watering:
      duration = scheduled_ms();
      break;
    case State::Cooldown:
      duration = config_.cooldown_ms;
      break;
    case State::Idle:
    case State::Error:
      return 0U;
  }
  const uint32_t spent = elapsed(now, state_started_at_);
  return spent >= duration ? 0U : duration - spent;
}

void WateringController::tick(uint32_t now) {
  switch (state_) {
    case State::BootGuard:
      if (elapsed(now, state_started_at_) >= config_.boot_guard_ms) {
        state_ = State::Idle;
        state_started_at_ = now;
      }
      break;
    case State::Watering: {
      const uint32_t runtime = elapsed(now, watering_started_at_);
      if (runtime >= active_duration_ms_) {
        finish_watering(now, "DOSE_COMPLETE");
      } else if (runtime >= config_.max_run_ms) {
        finish_watering(now, "MAX_RUN");
      }
      break;
    }
    case State::Cooldown:
      if (elapsed(now, state_started_at_) >= config_.cooldown_ms) {
        state_ = State::Idle;
        state_started_at_ = now;
      }
      break;
    case State::Idle:
    case State::Error:
      break;
  }
}

StartResult WateringController::start(const char* request_id, uint32_t now) {
  return start_with_duration(request_id, now, config_.dose_ms, true);
}

StartResult WateringController::start(const char* request_id, uint32_t now,
                                      uint32_t requested_duration_ms) {
  return start_with_duration(request_id, now, requested_duration_ms, false);
}

StartResult WateringController::start_with_duration(
    const char* request_id, uint32_t now, uint32_t requested_duration_ms,
    bool allow_safety_clamp) {
  if (!valid_request_id(request_id)) {
    return StartResult::InvalidRequest;
  }
  if (requested_duration_ms == 0U ||
      (!allow_safety_clamp && requested_duration_ms > config_.max_run_ms) ||
      requested_duration_ms > kAbsoluteMaxRunMs) {
    return StartResult::InvalidDuration;
  }
  if (is_duplicate(request_id)) {
    return StartResult::Duplicate;
  }
  switch (state_) {
    case State::BootGuard:
      return StartResult::BootGuard;
    case State::Watering:
      return StartResult::Busy;
    case State::Cooldown:
      return StartResult::Cooldown;
    case State::Error:
      return StartResult::Error;
    case State::Idle:
      break;
  }
  if (!config_.armed) {
    return StartResult::NotArmed;
  }

  last_request_id_ = request_id;
  remember_request(request_id);
  last_runtime_ms_ = 0U;
  last_stop_reason_.clear();
  error_reason_.clear();
  watering_started_at_ = now;
  state_started_at_ = now;
  active_duration_ms_ = requested_duration_ms;
  state_ = State::Watering;
  return StartResult::Accepted;
}

void WateringController::finish_watering(uint32_t now, const char* reason) {
  last_runtime_ms_ = elapsed(now, watering_started_at_);
  last_stop_reason_ = reason == nullptr ? "UNKNOWN" : reason;
  state_ = config_.cooldown_ms == 0U ? State::Idle : State::Cooldown;
  state_started_at_ = now;
}

void WateringController::stop(uint32_t now) {
  if (state_ == State::Watering) {
    finish_watering(now, "MANUAL_STOP");
  } else if (state_ == State::Idle && config_.cooldown_ms > 0U) {
    state_ = State::Cooldown;
    state_started_at_ = now;
  }
}

void WateringController::set_error(const char* reason, uint32_t now) {
  if (state_ == State::Watering) {
    last_runtime_ms_ = elapsed(now, watering_started_at_);
    last_stop_reason_ = "ERROR";
  }
  state_ = State::Error;
  state_started_at_ = now;
  error_reason_ = reason == nullptr ? "UNKNOWN_ERROR" : reason;
}

}  // namespace watering
