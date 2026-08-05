#include "sensor_filter.h"

#include <algorithm>
#include <array>

namespace watering {

uint16_t median_u16(const uint16_t* values, std::size_t count) {
  if (values == nullptr || count == 0U) {
    return 0U;
  }
  const std::size_t used = std::min(count, kMaximumMedianSamples);
  std::array<uint16_t, kMaximumMedianSamples> sorted{};
  std::copy_n(values, used, sorted.begin());
  std::sort(sorted.begin(), sorted.begin() + used);
  if ((used % 2U) == 1U) {
    return sorted[used / 2U];
  }
  const uint32_t pair_sum = static_cast<uint32_t>(sorted[(used / 2U) - 1U]) +
                            static_cast<uint32_t>(sorted[used / 2U]);
  return static_cast<uint16_t>(pair_sum / 2U);
}

}  // namespace watering
