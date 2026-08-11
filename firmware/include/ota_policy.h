#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "watering_controller.h"

namespace watering {

constexpr std::size_t kOtaDigestBytes = 32U;
constexpr std::size_t kOtaDigestHexLength = kOtaDigestBytes * 2U;
constexpr uint32_t kOtaNonceValidityMs = 60000U;

struct SemanticVersion {
  uint32_t major;
  uint32_t minor;
  uint32_t patch;
};

struct OtaMetadata {
  std::string target;
  std::string new_version;
  std::size_t size;
  std::string sha256;
  std::string nonce;
  std::string signature;
};

enum class OtaMetadataError {
  None,
  InvalidTarget,
  InvalidVersion,
  InvalidSize,
  InvalidSha256,
  InvalidNonce,
  InvalidSignature,
};

enum class OtaBootValidationDecision {
  Wait,
  Confirm,
  Rollback,
};

bool parse_strict_semver(const std::string& text, SemanticVersion& result);
bool is_strictly_newer_semver(const std::string& current,
                              const std::string& candidate);
bool is_lower_hex(const std::string& text, std::size_t expected_length);
bool parse_canonical_size(const std::string& text, std::size_t& result);
OtaMetadataError validate_ota_metadata(const OtaMetadata& metadata,
                                       const std::string& expected_target,
                                       const std::string& current_version,
                                       std::size_t maximum_firmware_bytes);
bool ota_safety_gate_allows(State controller_state, bool actual_pump_high,
                            bool hold_active, bool update_active,
                            bool reboot_pending);
OtaBootValidationDecision ota_boot_validation_decision(
    bool pending, uint32_t started_at, uint32_t now, uint32_t health_window_ms,
    bool wifi_connected, bool watchdog_ready, State controller_state,
    bool actual_pump_high);
bool bounded_deadline_is_in_future(uint32_t deadline, uint32_t now);
bool ota_upload_has_stalled(bool update_active, bool ready_to_finalize,
                            uint32_t last_activity_at, uint32_t now,
                            uint32_t timeout_ms);
bool nonce_is_fresh_and_matching(const std::string& expected,
                                 const std::string& provided,
                                 uint32_t issued_at, uint32_t now);
std::string encode_lower_hex(const uint8_t* bytes, std::size_t size);
bool decode_lower_hex(const std::string& text, uint8_t* output,
                      std::size_t output_size);
bool constant_time_bytes_equal(const uint8_t* expected, const uint8_t* actual,
                               std::size_t size);
std::string ota_canonical_message(const std::string& device_name,
                                  const std::string& target,
                                  const std::string& current_version,
                                  const std::string& new_version,
                                  std::size_t firmware_size,
                                  const std::string& sha256,
                                  const std::string& nonce);

}  // namespace watering
