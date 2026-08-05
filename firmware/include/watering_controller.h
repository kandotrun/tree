#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace watering {

constexpr uint32_t kAbsoluteMaxRunMs = 180000U;
constexpr std::size_t kRecentRequestCount = 8U;

enum class State {
  BootGuard,
  Idle,
  Watering,
  Cooldown,
  Error,
};

enum class StartResult {
  Accepted,
  InvalidRequest,
  Duplicate,
  BootGuard,
  Busy,
  Cooldown,
  Error,
  NotArmed,
};

struct ControllerConfig {
  uint32_t dose_ms;
  uint32_t max_run_ms;
  uint32_t cooldown_ms;
  uint32_t boot_guard_ms;
  bool armed;
};

const char* state_name(State state);

class WateringController {
 public:
  explicit WateringController(const ControllerConfig& config,
                              uint32_t boot_started_at,
                              const char* restored_request_id = nullptr);

  void tick(uint32_t now);
  StartResult start(const char* request_id, uint32_t now);
  void stop(uint32_t now);
  void set_error(const char* reason, uint32_t now);

  State state() const { return state_; }
  bool pump_on() const { return state_ == State::Watering; }
  uint32_t remaining_ms(uint32_t now) const;
  uint32_t scheduled_ms() const;
  uint32_t last_runtime_ms() const { return last_runtime_ms_; }
  const std::string& last_request_id() const { return last_request_id_; }
  const char* last_stop_reason() const { return last_stop_reason_.c_str(); }
  const char* error_reason() const { return error_reason_.c_str(); }

  static bool valid_request_id(const char* request_id);

 private:
  static uint32_t elapsed(uint32_t now, uint32_t since) { return now - since; }
  bool valid_config() const;
  bool is_duplicate(const char* request_id) const;
  void remember_request(const char* request_id);
  void finish_watering(uint32_t now, const char* reason);

  ControllerConfig config_;
  State state_;
  uint32_t state_started_at_;
  uint32_t watering_started_at_;
  uint32_t last_runtime_ms_;
  std::string last_request_id_;
  std::string last_stop_reason_;
  std::string error_reason_;
  std::array<std::string, kRecentRequestCount> recent_request_ids_{};
  std::size_t recent_request_size_ = 0U;
  std::size_t recent_request_next_ = 0U;
};

}  // namespace watering
