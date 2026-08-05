#pragma once

#include <atomic>

namespace watering {

class PumpSafetyGate {
 public:
  void arm() { cutoff_fired_.store(false); }
  void cutoff() { cutoff_fired_.store(true); }

  bool allows_output(bool controller_requests_output) const {
    return controller_requests_output && !cutoff_fired_.load();
  }

 private:
  std::atomic<bool> cutoff_fired_{true};
};

}  // namespace watering
