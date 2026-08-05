#include <cstdint>
#include <string>

#include <unity.h>

#include "api_contract.h"
#include "pump_safety_gate.h"
#include "sensor_filter.h"

using watering::HttpDecision;
using watering::PumpSafetyGate;
using watering::StartResult;
using watering::constant_time_equals;
using watering::http_decision;
using watering::median_u16;

namespace {

void test_start_results_have_stable_http_mapping() {
  HttpDecision decision = http_decision(StartResult::Accepted);
  TEST_ASSERT_EQUAL_INT(202, decision.status);
  TEST_ASSERT_EQUAL_STRING("accepted", decision.code);

  decision = http_decision(StartResult::InvalidRequest);
  TEST_ASSERT_EQUAL_INT(400, decision.status);
  TEST_ASSERT_EQUAL_STRING("invalid_request_id", decision.code);

  decision = http_decision(StartResult::Duplicate);
  TEST_ASSERT_EQUAL_INT(409, decision.status);
  TEST_ASSERT_EQUAL_STRING("duplicate_request_id", decision.code);

  decision = http_decision(StartResult::Busy);
  TEST_ASSERT_EQUAL_INT(409, decision.status);
  TEST_ASSERT_EQUAL_STRING("busy", decision.code);

  decision = http_decision(StartResult::BootGuard);
  TEST_ASSERT_EQUAL_INT(423, decision.status);
  TEST_ASSERT_EQUAL_STRING("boot_guard", decision.code);

  decision = http_decision(StartResult::Error);
  TEST_ASSERT_EQUAL_INT(423, decision.status);
  TEST_ASSERT_EQUAL_STRING("error", decision.code);

  decision = http_decision(StartResult::NotArmed);
  TEST_ASSERT_EQUAL_INT(423, decision.status);
  TEST_ASSERT_EQUAL_STRING("not_armed", decision.code);

  decision = http_decision(StartResult::Cooldown);
  TEST_ASSERT_EQUAL_INT(429, decision.status);
  TEST_ASSERT_EQUAL_STRING("cooldown", decision.code);
}

void test_constant_time_token_comparison_handles_mismatch_and_bounds() {
  TEST_ASSERT_TRUE(constant_time_equals("same-token", "same-token", 64U));
  TEST_ASSERT_FALSE(constant_time_equals("same-token", "Same-token", 64U));
  TEST_ASSERT_FALSE(constant_time_equals("same-token", "same-token-extra", 64U));
  TEST_ASSERT_FALSE(constant_time_equals(nullptr, "same-token", 64U));
  TEST_ASSERT_FALSE(constant_time_equals("same-token", nullptr, 64U));

  const std::string too_long(65U, 'a');
  TEST_ASSERT_FALSE(constant_time_equals(too_long.c_str(), too_long.c_str(), 64U));
}

void test_median_filter_rejects_single_large_outlier() {
  const uint16_t values[] = {1500U, 1501U, 1499U, 1502U, 4095U,
                             1498U, 1500U, 1503U, 1497U};

  TEST_ASSERT_EQUAL_UINT16(1500U, median_u16(values, 9U));
}

void test_median_filter_handles_empty_and_even_inputs() {
  const uint16_t values[] = {10U, 100U, 20U, 30U};

  TEST_ASSERT_EQUAL_UINT16(0U, median_u16(nullptr, 0U));
  TEST_ASSERT_EQUAL_UINT16(25U, median_u16(values, 4U));
}

void test_safety_cutoff_cannot_be_overridden_by_stale_controller_state() {
  PumpSafetyGate gate;
  TEST_ASSERT_FALSE(gate.allows_output(true));
  gate.arm();
  TEST_ASSERT_TRUE(gate.allows_output(true));

  gate.cutoff();

  TEST_ASSERT_FALSE(gate.allows_output(true));
  TEST_ASSERT_FALSE(gate.allows_output(false));
  gate.arm();
  TEST_ASSERT_TRUE(gate.allows_output(true));
}

}  // namespace

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_start_results_have_stable_http_mapping);
  RUN_TEST(test_constant_time_token_comparison_handles_mismatch_and_bounds);
  RUN_TEST(test_median_filter_rejects_single_large_outlier);
  RUN_TEST(test_median_filter_handles_empty_and_even_inputs);
  RUN_TEST(test_safety_cutoff_cannot_be_overridden_by_stale_controller_state);
  return UNITY_END();
}
