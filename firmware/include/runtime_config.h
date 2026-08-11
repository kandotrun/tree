#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace watering {

constexpr uint32_t kRuntimeAbsoluteMaxRunMs = 180000U;

struct RuntimeConfig {
  std::string wifi_ssid;
  std::string wifi_password;
  bool watering_armed;
  uint32_t dose_ms;
  uint32_t max_run_ms;
  uint32_t cooldown_ms;
  uint32_t boot_guard_ms;
};

struct ProvisioningRecord {
  bool present;
  uint32_t revision;
  RuntimeConfig config;
};

enum class ProvisioningAction {
  UseStored,
  PersistCompiled,
  FailClosed,
};

struct ProvisioningSelection {
  ProvisioningAction action;
  uint32_t revision;
  RuntimeConfig config;
};

bool valid_runtime_config(const RuntimeConfig& config);
RuntimeConfig fail_closed_runtime_config();
ProvisioningSelection select_runtime_config(
    const ProvisioningRecord& stored,
    const ProvisioningRecord& compiled);

}  // namespace watering
