#include "api_contract.h"

#include <cstdint>

namespace watering {

HttpDecision http_decision(StartResult result) {
  switch (result) {
    case StartResult::Accepted:
      return {202, "accepted"};
    case StartResult::InvalidRequest:
      return {400, "invalid_request_id"};
    case StartResult::InvalidDuration:
      return {400, "invalid_duration_sec"};
    case StartResult::Duplicate:
      return {409, "duplicate_request_id"};
    case StartResult::Busy:
      return {409, "busy"};
    case StartResult::BootGuard:
      return {423, "boot_guard"};
    case StartResult::Error:
      return {423, "error"};
    case StartResult::NotArmed:
      return {423, "not_armed"};
    case StartResult::Cooldown:
      return {429, "cooldown"};
  }
  return {423, "error"};
}

HttpDecision http_decision(HoldRenewResult result) {
  switch (result) {
    case HoldRenewResult::Renewed:
      return {200, "renewed"};
    case HoldRenewResult::InvalidRequest:
      return {400, "invalid_request_id"};
    case HoldRenewResult::NotActive:
      return {409, "hold_not_active"};
    case HoldRenewResult::SessionMismatch:
      return {409, "hold_session_mismatch"};
    case HoldRenewResult::Expired:
      return {409, "hold_expired"};
  }
  return {409, "hold_not_active"};
}

RequestedDuration resolve_requested_duration(bool provided, bool is_integer,
                                             uint64_t duration_sec,
                                             uint32_t default_duration_ms,
                                             uint32_t maximum_duration_ms) {
  if (!provided) {
    return {default_duration_ms > 0U &&
                default_duration_ms <= kAbsoluteMaxRunMs,
            default_duration_ms};
  }
  if (!is_integer || duration_sec == 0U ||
      duration_sec > static_cast<uint64_t>(kAbsoluteMaxRunMs / 1000U)) {
    return {false, 0U};
  }
  const uint32_t duration_ms = static_cast<uint32_t>(duration_sec * 1000U);
  if (duration_ms > maximum_duration_ms) {
    return {false, 0U};
  }
  return {true, duration_ms};
}

RequestedDuration resolve_requested_duration(
    JsonVariantConst duration_value, uint32_t default_duration_ms,
    uint32_t maximum_duration_ms) {
  const bool provided = !duration_value.isUnbound();
  const bool is_integer = duration_value.is<uint64_t>();
  const uint64_t duration_sec =
      is_integer ? duration_value.as<uint64_t>() : 0U;
  return resolve_requested_duration(provided, is_integer, duration_sec,
                                    default_duration_ms, maximum_duration_ms);
}

}  // namespace watering
