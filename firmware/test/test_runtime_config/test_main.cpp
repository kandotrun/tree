#include <cstdint>
#include <string>

#include <unity.h>

#include "runtime_config.h"

using watering::ProvisioningAction;
using watering::ProvisioningRecord;
using watering::ProvisioningSelection;
using watering::RuntimeConfig;

namespace {

RuntimeConfig valid_config(const char* ssid = "test-network") {
  return RuntimeConfig{
      ssid,
      "example-password",
      true,
      10000U,
      180000U,
      0U,
      300000U,
  };
}

ProvisioningRecord record(bool present, uint32_t revision,
                          const RuntimeConfig& config) {
  return ProvisioningRecord{present, revision, config};
}

void test_generic_revision_zero_preserves_valid_nvs_configuration() {
  const ProvisioningRecord stored = record(true, 7U, valid_config("stored"));
  RuntimeConfig placeholders = valid_config("CHANGE_ME");
  placeholders.wifi_password = "CHANGE_ME";
  const ProvisioningRecord compiled = record(true, 0U, placeholders);

  const ProvisioningSelection selected =
      watering::select_runtime_config(stored, compiled);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::UseStored),
                        static_cast<int>(selected.action));
  TEST_ASSERT_EQUAL_UINT32(7U, selected.revision);
  TEST_ASSERT_EQUAL_STRING("stored", selected.config.wifi_ssid.c_str());
  TEST_ASSERT_TRUE(selected.config.watering_armed);
}

void test_generic_revision_zero_without_nvs_fails_closed() {
  const ProvisioningRecord stored =
      record(false, 0U, watering::fail_closed_runtime_config());
  RuntimeConfig placeholders = valid_config("CHANGE_ME");
  placeholders.wifi_password = "CHANGE_ME";
  const ProvisioningRecord compiled = record(true, 0U, placeholders);

  const ProvisioningSelection selected =
      watering::select_runtime_config(stored, compiled);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::FailClosed),
                        static_cast<int>(selected.action));
  TEST_ASSERT_FALSE(selected.config.watering_armed);
  TEST_ASSERT_TRUE(selected.config.wifi_ssid.empty());
  TEST_ASSERT_EQUAL_UINT32(0U, selected.config.max_run_ms);
}

void test_only_higher_valid_compile_revision_requests_persistence() {
  const ProvisioningRecord stored = record(true, 3U, valid_config("stored"));
  RuntimeConfig updated = valid_config("updated");
  updated.dose_ms = 12000U;

  ProvisioningSelection selected = watering::select_runtime_config(
      stored, record(true, 4U, updated));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::PersistCompiled),
                        static_cast<int>(selected.action));
  TEST_ASSERT_EQUAL_UINT32(4U, selected.revision);
  TEST_ASSERT_EQUAL_STRING("updated", selected.config.wifi_ssid.c_str());
  TEST_ASSERT_EQUAL_UINT32(12000U, selected.config.dose_ms);

  selected =
      watering::select_runtime_config(stored, record(true, 3U, updated));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::UseStored),
                        static_cast<int>(selected.action));
  TEST_ASSERT_EQUAL_STRING("stored", selected.config.wifi_ssid.c_str());

  selected =
      watering::select_runtime_config(stored, record(true, 2U, updated));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::UseStored),
                        static_cast<int>(selected.action));
  TEST_ASSERT_EQUAL_STRING("stored", selected.config.wifi_ssid.c_str());
}

void test_invalid_higher_compile_revision_fails_closed() {
  const ProvisioningRecord stored = record(true, 3U, valid_config("stored"));
  RuntimeConfig invalid = valid_config("updated");
  invalid.max_run_ms = watering::kRuntimeAbsoluteMaxRunMs + 1U;

  const ProvisioningSelection selected = watering::select_runtime_config(
      stored, record(true, 99U, invalid));

  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::FailClosed),
                        static_cast<int>(selected.action));
  TEST_ASSERT_FALSE(selected.config.watering_armed);
  TEST_ASSERT_TRUE(selected.config.wifi_ssid.empty());
}

void test_first_valid_nonzero_compile_revision_can_seed_empty_nvs() {
  const ProvisioningRecord stored =
      record(false, 0U, watering::fail_closed_runtime_config());
  const ProvisioningRecord compiled = record(true, 1U, valid_config("local"));

  const ProvisioningSelection selected =
      watering::select_runtime_config(stored, compiled);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(ProvisioningAction::PersistCompiled),
                        static_cast<int>(selected.action));
  TEST_ASSERT_EQUAL_UINT32(1U, selected.revision);
  TEST_ASSERT_EQUAL_STRING("local", selected.config.wifi_ssid.c_str());
}

void test_runtime_validation_rejects_placeholders_and_unsafe_timers() {
  RuntimeConfig config = valid_config();
  TEST_ASSERT_TRUE(watering::valid_runtime_config(config));

  config.wifi_ssid = "replace_me";
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));

  config = valid_config();
  config.wifi_password.clear();
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));

  config = valid_config();
  config.dose_ms = 0U;
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));

  config = valid_config();
  config.dose_ms = config.max_run_ms + 1U;
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));

  config = valid_config();
  config.boot_guard_ms = 0U;
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));
}

void test_fail_closed_runtime_configuration_cannot_connect_or_water() {
  const RuntimeConfig config = watering::fail_closed_runtime_config();

  TEST_ASSERT_TRUE(config.wifi_ssid.empty());
  TEST_ASSERT_TRUE(config.wifi_password.empty());
  TEST_ASSERT_FALSE(config.watering_armed);
  TEST_ASSERT_EQUAL_UINT32(0U, config.dose_ms);
  TEST_ASSERT_EQUAL_UINT32(0U, config.max_run_ms);
  TEST_ASSERT_EQUAL_UINT32(0U, config.cooldown_ms);
  TEST_ASSERT_EQUAL_UINT32(0U, config.boot_guard_ms);
  TEST_ASSERT_FALSE(watering::valid_runtime_config(config));
}

}  // namespace

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_generic_revision_zero_preserves_valid_nvs_configuration);
  RUN_TEST(test_generic_revision_zero_without_nvs_fails_closed);
  RUN_TEST(test_only_higher_valid_compile_revision_requests_persistence);
  RUN_TEST(test_invalid_higher_compile_revision_fails_closed);
  RUN_TEST(test_first_valid_nonzero_compile_revision_can_seed_empty_nvs);
  RUN_TEST(test_runtime_validation_rejects_placeholders_and_unsafe_timers);
  RUN_TEST(test_fail_closed_runtime_configuration_cannot_connect_or_water);
  return UNITY_END();
}
