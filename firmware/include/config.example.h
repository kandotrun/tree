#pragma once

// Copy this file to config.h. Never commit config.h.
#define WIFI_SSID "CHANGE_ME"
#define WIFI_PASSWORD "CHANGE_ME"
#define API_TOKEN "CHANGE_ME_TO_AT_LEAST_32_RANDOM_ASCII_CHARACTERS"

#define DEVICE_NAME "balcony-watering"
#define FIRMWARE_VERSION "0.1.0"

#define PUMP_PIN 26
#define MOISTURE_PIN 32
#define LED_PIN 27

// Keep false until the outlet points into a measuring container and all
// preflight checks in docs/development-guide.md have passed.
#define WATERING_ARMED false

// Calibration-only starting values. Do not water the tree before measurement.
#define DOSE_MS 10000UL
#define MAX_RUN_MS 15000UL
#define COOLDOWN_MS 600000UL
#define BOOT_GUARD_MS 300000UL

#define WIFI_CONNECT_TIMEOUT_MS 20000UL
#define WIFI_RECONNECT_INTERVAL_MS 10000UL
#define MOISTURE_SAMPLE_INTERVAL_MS 1000UL
#define WATCHDOG_TIMEOUT_SEC 10
