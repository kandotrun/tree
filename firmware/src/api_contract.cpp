#include "api_contract.h"

#include <cstdint>

namespace watering {
namespace {

std::size_t bounded_length(const char* value, std::size_t maximum) {
  std::size_t length = 0U;
  while (length <= maximum && value[length] != '\0') {
    ++length;
  }
  return length;
}

}  // namespace

HttpDecision http_decision(StartResult result) {
  switch (result) {
    case StartResult::Accepted:
      return {202, "accepted"};
    case StartResult::InvalidRequest:
      return {400, "invalid_request_id"};
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

bool constant_time_equals(const char* left, const char* right,
                          std::size_t max_length) {
  if (left == nullptr || right == nullptr || max_length == 0U) {
    return false;
  }
  const std::size_t left_length = bounded_length(left, max_length);
  const std::size_t right_length = bounded_length(right, max_length);
  if (left_length > max_length || right_length > max_length) {
    return false;
  }

  uint32_t difference = static_cast<uint32_t>(left_length ^ right_length);
  for (std::size_t index = 0U; index < max_length; ++index) {
    const uint8_t left_character =
        index < left_length ? static_cast<uint8_t>(left[index]) : 0U;
    const uint8_t right_character =
        index < right_length ? static_cast<uint8_t>(right[index]) : 0U;
    difference |= static_cast<uint32_t>(left_character ^ right_character);
  }
  return difference == 0U;
}

}  // namespace watering
