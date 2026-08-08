#pragma once

#include <cstdint>

#include <ArduinoJson.h>

#include "watering_controller.h"

namespace watering {

struct HttpDecision {
  int status;
  const char* code;
};

struct RequestedDuration {
  bool valid;
  uint32_t duration_ms;
};

HttpDecision http_decision(StartResult result);
HttpDecision http_decision(HoldRenewResult result);
RequestedDuration resolve_requested_duration(bool provided, bool is_integer,
                                             uint64_t duration_sec,
                                             uint32_t default_duration_ms,
                                             uint32_t maximum_duration_ms);
RequestedDuration resolve_requested_duration(
    JsonVariantConst duration_value, uint32_t default_duration_ms,
    uint32_t maximum_duration_ms);
}  // namespace watering
