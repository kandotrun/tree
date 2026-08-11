#include "ota_policy.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>

namespace watering {
namespace {

bool parse_semver_component(const std::string& text, std::size_t start,
                            std::size_t end, uint32_t& value) {
  if (start >= end || (end - start > 1U && text[start] == '0')) {
    return false;
  }
  uint32_t parsed = 0U;
  for (std::size_t index = start; index < end; ++index) {
    const char character = text[index];
    if (character < '0' || character > '9') {
      return false;
    }
    const uint32_t digit = static_cast<uint32_t>(character - '0');
    if (parsed > (std::numeric_limits<uint32_t>::max() - digit) / 10U) {
      return false;
    }
    parsed = parsed * 10U + digit;
  }
  value = parsed;
  return true;
}

int compare_semver(const SemanticVersion& left, const SemanticVersion& right) {
  const std::array<uint32_t, 3U> left_parts = {left.major, left.minor,
                                               left.patch};
  const std::array<uint32_t, 3U> right_parts = {right.major, right.minor,
                                                right.patch};
  for (std::size_t index = 0U; index < left_parts.size(); ++index) {
    if (left_parts[index] < right_parts[index]) {
      return -1;
    }
    if (left_parts[index] > right_parts[index]) {
      return 1;
    }
  }
  return 0;
}

uint8_t hex_value(char character) {
  return character >= '0' && character <= '9'
             ? static_cast<uint8_t>(character - '0')
             : static_cast<uint8_t>(character - 'a' + 10);
}

}  // namespace

bool parse_strict_semver(const std::string& text, SemanticVersion& result) {
  const std::size_t first_dot = text.find('.');
  if (first_dot == std::string::npos) {
    return false;
  }
  const std::size_t second_dot = text.find('.', first_dot + 1U);
  if (second_dot == std::string::npos ||
      text.find('.', second_dot + 1U) != std::string::npos) {
    return false;
  }

  SemanticVersion parsed{};
  if (!parse_semver_component(text, 0U, first_dot, parsed.major) ||
      !parse_semver_component(text, first_dot + 1U, second_dot, parsed.minor) ||
      !parse_semver_component(text, second_dot + 1U, text.size(),
                              parsed.patch)) {
    return false;
  }
  result = parsed;
  return true;
}

bool is_strictly_newer_semver(const std::string& current,
                              const std::string& candidate) {
  SemanticVersion parsed_current{};
  SemanticVersion parsed_candidate{};
  return parse_strict_semver(current, parsed_current) &&
         parse_strict_semver(candidate, parsed_candidate) &&
         compare_semver(parsed_current, parsed_candidate) < 0;
}

bool is_lower_hex(const std::string& text, std::size_t expected_length) {
  if (text.size() != expected_length) {
    return false;
  }
  for (const char character : text) {
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool parse_canonical_size(const std::string& text, std::size_t& result) {
  if (text.empty() || text == "0" || (text.size() > 1U && text[0] == '0')) {
    return false;
  }
  std::size_t parsed = 0U;
  for (const char character : text) {
    if (character < '0' || character > '9') {
      return false;
    }
    const std::size_t digit = static_cast<std::size_t>(character - '0');
    if (parsed > (std::numeric_limits<std::size_t>::max() - digit) / 10U) {
      return false;
    }
    parsed = parsed * 10U + digit;
  }
  result = parsed;
  return true;
}

OtaMetadataError validate_ota_metadata(const OtaMetadata& metadata,
                                       const std::string& expected_target,
                                       const std::string& current_version,
                                       std::size_t maximum_firmware_bytes) {
  if (expected_target.empty() || metadata.target != expected_target) {
    return OtaMetadataError::InvalidTarget;
  }
  if (!is_strictly_newer_semver(current_version, metadata.new_version)) {
    return OtaMetadataError::InvalidVersion;
  }
  if (metadata.size == 0U || maximum_firmware_bytes == 0U ||
      metadata.size > maximum_firmware_bytes) {
    return OtaMetadataError::InvalidSize;
  }
  if (!is_lower_hex(metadata.sha256, kOtaDigestHexLength)) {
    return OtaMetadataError::InvalidSha256;
  }
  if (!is_lower_hex(metadata.nonce, kOtaDigestHexLength)) {
    return OtaMetadataError::InvalidNonce;
  }
  if (!is_lower_hex(metadata.signature, kOtaDigestHexLength)) {
    return OtaMetadataError::InvalidSignature;
  }
  return OtaMetadataError::None;
}

bool ota_safety_gate_allows(State controller_state, bool actual_pump_high,
                            bool hold_active, bool update_active,
                            bool reboot_pending) {
  return controller_state == State::Idle && !actual_pump_high && !hold_active &&
         !update_active && !reboot_pending;
}

OtaBootValidationDecision ota_boot_validation_decision(
    bool pending, uint32_t started_at, uint32_t now, uint32_t health_window_ms,
    bool wifi_connected, bool watchdog_ready, State controller_state,
    bool actual_pump_high) {
  if (!pending || now - started_at < health_window_ms) {
    return OtaBootValidationDecision::Wait;
  }
  if (wifi_connected && watchdog_ready && controller_state != State::Error &&
      !actual_pump_high) {
    return OtaBootValidationDecision::Confirm;
  }
  return OtaBootValidationDecision::Rollback;
}

bool bounded_deadline_is_in_future(uint32_t deadline, uint32_t now) {
  return deadline != 0U && static_cast<int32_t>(deadline - now) > 0;
}

bool ota_upload_has_stalled(bool update_active, bool ready_to_finalize,
                            uint32_t last_activity_at, uint32_t now,
                            uint32_t timeout_ms) {
  return update_active && !ready_to_finalize && timeout_ms > 0U &&
         now - last_activity_at >= timeout_ms;
}

bool nonce_is_fresh_and_matching(const std::string& expected,
                                 const std::string& provided,
                                 uint32_t issued_at, uint32_t now) {
  if (!is_lower_hex(expected, kOtaDigestHexLength) ||
      !is_lower_hex(provided, kOtaDigestHexLength) ||
      expected.size() != provided.size() || now - issued_at >= kOtaNonceValidityMs) {
    return false;
  }
  uint8_t difference = 0U;
  for (std::size_t index = 0U; index < expected.size(); ++index) {
    difference |= static_cast<uint8_t>(expected[index] ^ provided[index]);
  }
  return difference == 0U;
}

std::string encode_lower_hex(const uint8_t* bytes, std::size_t size) {
  static constexpr char kHex[] = "0123456789abcdef";
  if (bytes == nullptr && size > 0U) {
    return "";
  }
  std::string result;
  result.resize(size * 2U);
  for (std::size_t index = 0U; index < size; ++index) {
    result[index * 2U] = kHex[bytes[index] >> 4U];
    result[index * 2U + 1U] = kHex[bytes[index] & 0x0fU];
  }
  return result;
}

bool decode_lower_hex(const std::string& text, uint8_t* output,
                      std::size_t output_size) {
  if (output == nullptr || !is_lower_hex(text, output_size * 2U)) {
    return false;
  }
  for (std::size_t index = 0U; index < output_size; ++index) {
    output[index] = static_cast<uint8_t>(
        (hex_value(text[index * 2U]) << 4U) |
        hex_value(text[index * 2U + 1U]));
  }
  return true;
}

bool constant_time_bytes_equal(const uint8_t* expected, const uint8_t* actual,
                               std::size_t size) {
  if (expected == nullptr || actual == nullptr) {
    return false;
  }
  uint8_t difference = 0U;
  for (std::size_t index = 0U; index < size; ++index) {
    difference |= static_cast<uint8_t>(expected[index] ^ actual[index]);
  }
  return difference == 0U;
}

std::string ota_canonical_message(const std::string& device_name,
                                  const std::string& target,
                                  const std::string& current_version,
                                  const std::string& new_version,
                                  std::size_t firmware_size,
                                  const std::string& sha256,
                                  const std::string& nonce) {
  return "tree-watering-ota-v1\n" + device_name + "\n" + target + "\n" +
         current_version + "\n" + new_version + "\n" +
         std::to_string(firmware_size) + "\n" + sha256 + "\n" + nonce;
}

}  // namespace watering
