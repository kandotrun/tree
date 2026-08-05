#pragma once

#include <cstddef>
#include <cstdint>

namespace watering {

constexpr std::size_t kMaximumMedianSamples = 15U;

uint16_t median_u16(const uint16_t* values, std::size_t count);

}  // namespace watering
