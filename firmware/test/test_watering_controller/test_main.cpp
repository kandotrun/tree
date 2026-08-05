#include <cstdint>
#include <limits>
#include <string>

#include <unity.h>

#include "watering_controller.h"

using watering::ControllerConfig;
using watering::StartResult;
using watering::State;
using watering::WateringController;

namespace {

ControllerConfig safe_config(bool armed = true) {
  return ControllerConfig{
      10000U,   // dose_ms
      15000U,   // max_run_ms
      600000U,  // cooldown_ms
      300000U,  // boot_guard_ms
      armed,
  };
}

void advance_to_idle(WateringController& controller, uint32_t boot_time = 0U) {
  controller.tick(boot_time + 300000U);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Idle), static_cast<int>(controller.state()));
}

void test_boot_guard_keeps_pump_off_until_boundary() {
  WateringController controller(safe_config(), 100U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::BootGuard),
                        static_cast<int>(controller.state()));
  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_UINT32(1U, controller.remaining_ms(300099U));

  controller.tick(300100U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Idle), static_cast<int>(controller.state()));
  TEST_ASSERT_FALSE(controller.pump_on());
}

void test_boot_guard_rejects_water_request() {
  WateringController controller(safe_config(), 0U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::BootGuard),
                        static_cast<int>(controller.start("request-1", 1000U)));
  TEST_ASSERT_FALSE(controller.pump_on());
}

void test_unarmed_controller_rejects_after_boot_guard() {
  WateringController controller(safe_config(false), 0U);
  advance_to_idle(controller);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::NotArmed),
                        static_cast<int>(controller.start("request-1", 300001U)));
  TEST_ASSERT_FALSE(controller.pump_on());
}

void test_valid_request_starts_one_fixed_dose() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Accepted),
                        static_cast<int>(controller.start("request-1", 300001U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Watering),
                        static_cast<int>(controller.state()));
  TEST_ASSERT_TRUE(controller.pump_on());
  TEST_ASSERT_EQUAL_STRING("request-1", controller.last_request_id().c_str());
  TEST_ASSERT_EQUAL_UINT32(10000U, controller.remaining_ms(300001U));
}

void test_dose_timer_stops_locally_without_network() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);
  controller.start("request-1", 300001U);

  controller.tick(310000U);
  TEST_ASSERT_TRUE(controller.pump_on());
  controller.tick(310001U);

  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Cooldown),
                        static_cast<int>(controller.state()));
  TEST_ASSERT_EQUAL_UINT32(10000U, controller.last_runtime_ms());
  TEST_ASSERT_EQUAL_STRING("DOSE_COMPLETE", controller.last_stop_reason());
}

void test_absolute_max_runtime_wins_if_dose_is_longer() {
  ControllerConfig config = safe_config();
  config.dose_ms = 20000U;
  WateringController controller(config, 0U);
  advance_to_idle(controller);
  controller.start("request-1", 300001U);

  controller.tick(315001U);

  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_UINT32(15000U, controller.last_runtime_ms());
  TEST_ASSERT_EQUAL_STRING("MAX_RUN", controller.last_stop_reason());
}

void test_manual_stop_is_immediate_and_enters_cooldown() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);
  controller.start("request-1", 300001U);

  controller.stop(302001U);

  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Cooldown),
                        static_cast<int>(controller.state()));
  TEST_ASSERT_EQUAL_UINT32(2000U, controller.last_runtime_ms());
  TEST_ASSERT_EQUAL_STRING("MANUAL_STOP", controller.last_stop_reason());
}

void test_stop_while_idle_enters_cooldown_without_claiming_runtime() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);

  controller.stop(300001U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Cooldown),
                        static_cast<int>(controller.state()));
  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_UINT32(0U, controller.last_runtime_ms());
  TEST_ASSERT_EQUAL_STRING("", controller.last_stop_reason());
}

void test_busy_cooldown_and_duplicate_requests_are_rejected() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);
  controller.start("request-1", 300001U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Busy),
                        static_cast<int>(controller.start("request-2", 300002U)));
  controller.tick(310001U);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Duplicate),
                        static_cast<int>(controller.start("request-1", 310002U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Cooldown),
                        static_cast<int>(controller.start("request-2", 310002U)));

  controller.tick(910001U);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Duplicate),
                        static_cast<int>(controller.start("request-1", 910002U)));
}

void test_restored_request_id_is_rejected_after_reboot() {
  WateringController controller(safe_config(), 0U, "persisted-request");
  advance_to_idle(controller);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Duplicate),
                        static_cast<int>(controller.start("persisted-request", 300001U)));
}

void test_invalid_request_ids_are_rejected() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);
  std::string too_long(65U, 'a');

  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::InvalidRequest),
                        static_cast<int>(controller.start("", 300001U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::InvalidRequest),
                        static_cast<int>(controller.start("has space", 300001U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::InvalidRequest),
                        static_cast<int>(controller.start("slash/not-allowed", 300001U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::InvalidRequest),
                        static_cast<int>(controller.start(too_long.c_str(), 300001U)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Accepted),
                        static_cast<int>(controller.start("AZaz09_-", 300001U)));
}

void test_millis_rollover_preserves_timers() {
  const uint32_t boot_time = std::numeric_limits<uint32_t>::max() - 100U;
  ControllerConfig config = safe_config();
  config.boot_guard_ms = 200U;
  config.dose_ms = 300U;
  WateringController controller(config, boot_time);

  controller.tick(99U);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Idle), static_cast<int>(controller.state()));
  controller.start("request-1", 100U);
  controller.tick(399U);
  TEST_ASSERT_TRUE(controller.pump_on());
  controller.tick(400U);
  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_UINT32(300U, controller.last_runtime_ms());
}

void test_error_transition_always_turns_pump_off() {
  WateringController controller(safe_config(), 0U);
  advance_to_idle(controller);
  controller.start("request-1", 300001U);

  controller.set_error("NVS_WRITE_FAILED", 301001U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Error), static_cast<int>(controller.state()));
  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_STRING("NVS_WRITE_FAILED", controller.error_reason());
  TEST_ASSERT_EQUAL_INT(static_cast<int>(StartResult::Error),
                        static_cast<int>(controller.start("request-2", 301002U)));
}

void test_invalid_safety_configuration_starts_in_error() {
  ControllerConfig config = safe_config();
  config.max_run_ms = 180001U;

  WateringController controller(config, 0U);

  TEST_ASSERT_EQUAL_INT(static_cast<int>(State::Error), static_cast<int>(controller.state()));
  TEST_ASSERT_FALSE(controller.pump_on());
  TEST_ASSERT_EQUAL_STRING("INVALID_CONFIG", controller.error_reason());
}

}  // namespace

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_boot_guard_keeps_pump_off_until_boundary);
  RUN_TEST(test_boot_guard_rejects_water_request);
  RUN_TEST(test_unarmed_controller_rejects_after_boot_guard);
  RUN_TEST(test_valid_request_starts_one_fixed_dose);
  RUN_TEST(test_dose_timer_stops_locally_without_network);
  RUN_TEST(test_absolute_max_runtime_wins_if_dose_is_longer);
  RUN_TEST(test_manual_stop_is_immediate_and_enters_cooldown);
  RUN_TEST(test_stop_while_idle_enters_cooldown_without_claiming_runtime);
  RUN_TEST(test_busy_cooldown_and_duplicate_requests_are_rejected);
  RUN_TEST(test_restored_request_id_is_rejected_after_reboot);
  RUN_TEST(test_invalid_request_ids_are_rejected);
  RUN_TEST(test_millis_rollover_preserves_timers);
  RUN_TEST(test_error_transition_always_turns_pump_off);
  RUN_TEST(test_invalid_safety_configuration_starts_in_error);
  return UNITY_END();
}
