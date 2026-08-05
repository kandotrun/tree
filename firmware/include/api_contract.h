#pragma once

#include <cstddef>

#include "watering_controller.h"

namespace watering {

struct HttpDecision {
  int status;
  const char* code;
};

HttpDecision http_decision(StartResult result);
bool constant_time_equals(const char* left, const char* right,
                          std::size_t max_length);

}  // namespace watering
