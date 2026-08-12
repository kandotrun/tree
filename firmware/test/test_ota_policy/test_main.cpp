#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>

#include <unity.h>

#include "ota_policy.h"

using watering::OtaMetadata;
using watering::OtaMetadataError;
using watering::OtaBootValidationDecision;
using watering::SemanticVersion;

namespace {

OtaMetadata valid_metadata() {
  return OtaMetadata{
      "m5stack-atom",
      "0.6.1",
      4096U,
      std::string(64U, 'a'),
      std::string(64U, 'b'),
      std::string(64U, 'c'),
  };
}

void test_strict_semver_accepts_three_numeric_components() {
  SemanticVersion version{};

  TEST_ASSERT_TRUE(watering::parse_strict_semver("0.6.0", version));
  TEST_ASSERT_EQUAL_UINT32(0U, version.major);
  TEST_ASSERT_EQUAL_UINT32(6U, version.minor);
  TEST_ASSERT_EQUAL_UINT32(0U, version.patch);
  TEST_ASSERT_TRUE(
      watering::parse_strict_semver("4294967295.0.1", version));
}

void test_strict_semver_rejects_malformed_or_overflowing_versions() {
  const char* malformed[] = {
      "",          "1",          "1.2",       "1.2.3.4",
      "01.2.3",    "1.02.3",     "1.2.03",    "v1.2.3",
      "1.2.3-rc1", "1.2.3+meta", "1.2.-1",    "1.2. 3",
      "4294967296.0.1",
  };
  SemanticVersion version{};

  for (const char* value : malformed) {
    TEST_ASSERT_FALSE(watering::parse_strict_semver(value, version));
  }
}

void test_only_strictly_newer_semver_is_accepted() {
  TEST_ASSERT_TRUE(watering::is_strictly_newer_semver("0.6.0", "0.6.1"));
  TEST_ASSERT_TRUE(watering::is_strictly_newer_semver("0.6.9", "0.7.0"));
  TEST_ASSERT_TRUE(watering::is_strictly_newer_semver("9.9.9", "10.0.0"));
  TEST_ASSERT_FALSE(watering::is_strictly_newer_semver("0.6.0", "0.6.0"));
  TEST_ASSERT_FALSE(watering::is_strictly_newer_semver("0.6.1", "0.6.0"));
  TEST_ASSERT_FALSE(watering::is_strictly_newer_semver("invalid", "0.6.1"));
  TEST_ASSERT_FALSE(watering::is_strictly_newer_semver("0.6.0", "invalid"));
}

void test_metadata_accepts_exact_target_size_and_lowercase_digests() {
  const OtaMetadata metadata = valid_metadata();

  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::None),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));
}

void test_metadata_rejects_wrong_target_or_non_newer_version() {
  OtaMetadata metadata = valid_metadata();
  metadata.target = "esp32";
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidTarget),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));

  metadata = valid_metadata();
  metadata.new_version = "0.6.0";
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidVersion),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));
}

void test_metadata_rejects_zero_or_oversized_firmware() {
  OtaMetadata metadata = valid_metadata();
  metadata.size = 0U;
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidSize),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));

  metadata = valid_metadata();
  metadata.size = 0x140001U;
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidSize),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));

  metadata = valid_metadata();
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidSize),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0U)));
}

void test_metadata_rejects_malformed_sha_nonce_and_signature() {
  OtaMetadata metadata = valid_metadata();
  metadata.sha256[0] = 'A';
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidSha256),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));

  metadata = valid_metadata();
  metadata.nonce.pop_back();
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidNonce),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));

  metadata = valid_metadata();
  metadata.signature[12] = 'g';
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaMetadataError::InvalidSignature),
      static_cast<int>(watering::validate_ota_metadata(
          metadata, "m5stack-atom", "0.6.0", 0x140000U)));
}

void test_decimal_size_parser_is_canonical_and_bounded() {
  std::size_t parsed = 0U;
  TEST_ASSERT_TRUE(watering::parse_canonical_size("1", parsed));
  TEST_ASSERT_EQUAL_UINT32(1U, parsed);
  TEST_ASSERT_TRUE(watering::parse_canonical_size("1310720", parsed));
  TEST_ASSERT_EQUAL_UINT32(1310720U, parsed);

  TEST_ASSERT_FALSE(watering::parse_canonical_size("", parsed));
  TEST_ASSERT_FALSE(watering::parse_canonical_size("0", parsed));
  TEST_ASSERT_FALSE(watering::parse_canonical_size("01", parsed));
  TEST_ASSERT_FALSE(watering::parse_canonical_size("+1", parsed));
  TEST_ASSERT_FALSE(watering::parse_canonical_size("1 ", parsed));
  TEST_ASSERT_FALSE(watering::parse_canonical_size(
      "999999999999999999999999999999999", parsed));
}

void test_ota_gate_requires_idle_actual_low_and_no_conflicting_operation() {
  TEST_ASSERT_TRUE(watering::ota_safety_gate_allows(
      watering::State::Idle, false, false, false, false));
  TEST_ASSERT_FALSE(watering::ota_safety_gate_allows(
      watering::State::Watering, false, false, false, false));
  TEST_ASSERT_FALSE(watering::ota_safety_gate_allows(
      watering::State::Idle, true, false, false, false));
  TEST_ASSERT_FALSE(watering::ota_safety_gate_allows(
      watering::State::Idle, false, true, false, false));
  TEST_ASSERT_FALSE(watering::ota_safety_gate_allows(
      watering::State::Idle, false, false, true, false));
  TEST_ASSERT_FALSE(watering::ota_safety_gate_allows(
      watering::State::Idle, false, false, false, true));
}

void test_nonce_must_match_and_be_younger_than_sixty_seconds() {
  const std::string nonce(64U, 'a');
  TEST_ASSERT_TRUE(
      watering::nonce_is_fresh_and_matching(nonce, nonce, 100U, 60099U));
  TEST_ASSERT_FALSE(
      watering::nonce_is_fresh_and_matching(nonce, nonce, 100U, 60100U));
  TEST_ASSERT_FALSE(watering::nonce_is_fresh_and_matching(
      nonce, std::string(64U, 'b'), 100U, 101U));
  TEST_ASSERT_FALSE(watering::nonce_is_fresh_and_matching(
      std::string(63U, 'a'), std::string(63U, 'a'), 100U, 101U));
}

void test_nonce_freshness_survives_millis_rollover() {
  const std::string nonce(64U, 'f');
  const uint32_t issued = std::numeric_limits<uint32_t>::max() - 100U;

  TEST_ASSERT_TRUE(
      watering::nonce_is_fresh_and_matching(nonce, nonce, issued, 49U));
}

void test_hex_codec_accepts_only_exact_lowercase_bytes() {
  const uint8_t bytes[] = {0x00U, 0x0fU, 0x10U, 0xabU, 0xffU};
  const std::string encoded = watering::encode_lower_hex(bytes, 5U);
  TEST_ASSERT_EQUAL_STRING("000f10abff", encoded.c_str());

  uint8_t decoded[5] = {};
  TEST_ASSERT_TRUE(watering::decode_lower_hex(encoded, decoded, 5U));
  TEST_ASSERT_EQUAL_UINT8_ARRAY(bytes, decoded, 5U);
  TEST_ASSERT_FALSE(watering::decode_lower_hex("000F10abff", decoded, 5U));
  TEST_ASSERT_FALSE(watering::decode_lower_hex("000f10ab", decoded, 5U));
}

void test_constant_time_byte_comparison_reports_exact_match() {
  const uint8_t expected[] = {1U, 2U, 3U, 4U};
  const uint8_t matching[] = {1U, 2U, 3U, 4U};
  const uint8_t different[] = {1U, 2U, 3U, 5U};

  TEST_ASSERT_TRUE(
      watering::constant_time_bytes_equal(expected, matching, 4U));
  TEST_ASSERT_FALSE(
      watering::constant_time_bytes_equal(expected, different, 4U));
  TEST_ASSERT_FALSE(watering::constant_time_bytes_equal(nullptr, matching, 4U));
}

void test_canonical_hmac_message_is_byte_exact() {
  const std::string canonical = watering::ota_canonical_message(
      "balcony-watering", "m5stack-atom", "0.6.0", "0.7.0", 4096U,
      std::string(64U, 'a'), std::string(64U, 'b'));
  const std::string expected =
      "tree-watering-ota-v1\n"
      "balcony-watering\n"
      "m5stack-atom\n"
      "0.6.0\n"
      "0.7.0\n"
      "4096\n" +
      std::string(64U, 'a') + "\n" + std::string(64U, 'b');

  TEST_ASSERT_EQUAL_STRING(expected.c_str(), canonical.c_str());
  TEST_ASSERT_EQUAL_CHAR('b', canonical.back());
}

void test_boot_validation_waits_until_health_window_expires() {
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Wait),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15099U, 15000U, true, true,
          watering::State::BootGuard, false)));
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Wait),
      static_cast<int>(watering::ota_boot_validation_decision(
          false, 100U, 99999U, 15000U, true, true,
          watering::State::Idle, false)));
}

void test_boot_validation_confirms_only_healthy_connected_firmware() {
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Confirm),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15100U, 15000U, true, true,
          watering::State::BootGuard, false)));

  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Rollback),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15100U, 15000U, false, true,
          watering::State::BootGuard, false)));
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Rollback),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15100U, 15000U, true, false,
          watering::State::BootGuard, false)));
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Rollback),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15100U, 15000U, true, true,
          watering::State::Error, false)));
  TEST_ASSERT_EQUAL_INT(
      static_cast<int>(OtaBootValidationDecision::Rollback),
      static_cast<int>(watering::ota_boot_validation_decision(
          true, 100U, 15100U, 15000U, true, true,
          watering::State::Idle, true)));
}

void test_bounded_deadline_rejects_zero_sentinel_and_survives_rollover() {
  TEST_ASSERT_FALSE(watering::bounded_deadline_is_in_future(
      0U, std::numeric_limits<uint32_t>::max() / 2U + 1U));
  TEST_ASSERT_FALSE(watering::bounded_deadline_is_in_future(100U, 100U));
  TEST_ASSERT_FALSE(watering::bounded_deadline_is_in_future(99U, 100U));
  TEST_ASSERT_TRUE(watering::bounded_deadline_is_in_future(200U, 100U));
  TEST_ASSERT_TRUE(watering::bounded_deadline_is_in_future(
      49U, std::numeric_limits<uint32_t>::max() - 100U));
}

void test_ota_upload_timeout_requires_active_stalled_nonfinal_upload() {
  TEST_ASSERT_FALSE(watering::ota_upload_has_stalled(
      false, false, 100U, 30100U, 30000U));
  TEST_ASSERT_FALSE(watering::ota_upload_has_stalled(
      true, true, 100U, 30100U, 30000U));
  TEST_ASSERT_FALSE(watering::ota_upload_has_stalled(
      true, false, 100U, 30099U, 30000U));
  TEST_ASSERT_TRUE(watering::ota_upload_has_stalled(
      true, false, 100U, 30100U, 30000U));

  const uint32_t before_rollover =
      std::numeric_limits<uint32_t>::max() - 100U;
  TEST_ASSERT_TRUE(watering::ota_upload_has_stalled(
      true, false, before_rollover, 29899U, 30000U));
  TEST_ASSERT_FALSE(watering::ota_upload_has_stalled(
      true, false, before_rollover, 29899U, 0U));
}

}  // namespace

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_strict_semver_accepts_three_numeric_components);
  RUN_TEST(test_strict_semver_rejects_malformed_or_overflowing_versions);
  RUN_TEST(test_only_strictly_newer_semver_is_accepted);
  RUN_TEST(test_metadata_accepts_exact_target_size_and_lowercase_digests);
  RUN_TEST(test_metadata_rejects_wrong_target_or_non_newer_version);
  RUN_TEST(test_metadata_rejects_zero_or_oversized_firmware);
  RUN_TEST(test_metadata_rejects_malformed_sha_nonce_and_signature);
  RUN_TEST(test_decimal_size_parser_is_canonical_and_bounded);
  RUN_TEST(test_ota_gate_requires_idle_actual_low_and_no_conflicting_operation);
  RUN_TEST(test_nonce_must_match_and_be_younger_than_sixty_seconds);
  RUN_TEST(test_nonce_freshness_survives_millis_rollover);
  RUN_TEST(test_hex_codec_accepts_only_exact_lowercase_bytes);
  RUN_TEST(test_constant_time_byte_comparison_reports_exact_match);
  RUN_TEST(test_canonical_hmac_message_is_byte_exact);
  RUN_TEST(test_boot_validation_waits_until_health_window_expires);
  RUN_TEST(test_boot_validation_confirms_only_healthy_connected_firmware);
  RUN_TEST(test_bounded_deadline_rejects_zero_sentinel_and_survives_rollover);
  RUN_TEST(test_ota_upload_timeout_requires_active_stalled_nonfinal_upload);
  return UNITY_END();
}
