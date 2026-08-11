#include "runtime_config.h"

#include <algorithm>
#include <cctype>
#include <string>

namespace watering {
namespace {

bool contains_placeholder(const std::string& value) {
  if (value.empty()) {
    return true;
  }
  std::string uppercase(value);
  std::transform(uppercase.begin(), uppercase.end(), uppercase.begin(),
                 [](unsigned char character) {
                   return static_cast<char>(std::toupper(character));
                 });
  return uppercase.find("CHANGE_ME") != std::string::npos ||
         uppercase.find("REPLACE_ME") != std::string::npos;
}

bool valid_stored_record(const ProvisioningRecord& record) {
  return record.present && record.revision > 0U &&
         valid_runtime_config(record.config);
}

}  // namespace

bool valid_runtime_config(const RuntimeConfig& config) {
  return !contains_placeholder(config.wifi_ssid) &&
         !contains_placeholder(config.wifi_password) &&
         config.wifi_ssid.size() <= 32U &&
         config.wifi_password.size() <= 63U && config.dose_ms > 0U &&
         config.dose_ms <= config.max_run_ms && config.max_run_ms > 0U &&
         config.max_run_ms <= kRuntimeAbsoluteMaxRunMs &&
         config.boot_guard_ms > 0U;
}

RuntimeConfig fail_closed_runtime_config() {
  return RuntimeConfig{"", "", false, 0U, 0U, 0U, 0U};
}

ProvisioningSelection select_runtime_config(
    const ProvisioningRecord& stored,
    const ProvisioningRecord& compiled) {
  const uint32_t stored_revision = stored.present ? stored.revision : 0U;
  if (compiled.present && compiled.revision > stored_revision) {
    if (compiled.revision > 0U && valid_runtime_config(compiled.config)) {
      return ProvisioningSelection{ProvisioningAction::PersistCompiled,
                                   compiled.revision, compiled.config};
    }
    return ProvisioningSelection{ProvisioningAction::FailClosed, 0U,
                                 fail_closed_runtime_config()};
  }
  if (valid_stored_record(stored)) {
    return ProvisioningSelection{ProvisioningAction::UseStored, stored.revision,
                                 stored.config};
  }
  return ProvisioningSelection{ProvisioningAction::FailClosed, 0U,
                               fail_closed_runtime_config()};
}

}  // namespace watering
