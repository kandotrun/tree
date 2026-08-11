#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <Update.h>
#include <WebServer.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

#include <atomic>
#include <array>
#include <memory>
#include <string>

#include "api_contract.h"
#include "config.h"
#include "dashboard_page.generated.h"
#include "firmware_identity.h"
#include "ota_policy.h"
#include "pump_safety_gate.h"
#include "runtime_config.h"
#include "sensor_filter.h"
#include "watering_controller.h"

#ifndef PROVISIONING_REVISION
#define PROVISIONING_REVISION 1U
#endif

#ifndef ATOM_BUTTON_PIN
#define ATOM_BUTTON_PIN 39
#endif

namespace {

using watering::ControllerConfig;
using watering::HoldRenewResult;
using watering::HttpDecision;
using watering::OtaMetadata;
using watering::OtaMetadataError;
using watering::PumpSafetyGate;
using watering::RequestedDuration;
using watering::StartResult;
using watering::State;
using watering::RuntimeConfig;
using watering::WateringController;

constexpr uint16_t kHttpPort = 80U;
constexpr char kDiscoveryServiceType[] = "tree-watering";
constexpr std::size_t kMaximumRequestBodyBytes = 256U;
constexpr std::size_t kMoistureSampleCount = 9U;
static_assert(kMoistureSampleCount <= watering::kMaximumMedianSamples);
constexpr uint32_t kSuccessLedMs = 1000U;
constexpr uint32_t kMDNSRetryIntervalMs = 5000U;
constexpr uint8_t kLedBrightness = 24U;
constexpr char kPreferencesNamespace[] = "watering";
constexpr char kLastRequestKey[] = "last_request";
constexpr char kProvisioningRevisionKey[] = "cfg_rev";
constexpr char kWifiSsidKey[] = "wifi_ssid";
constexpr char kWifiPasswordKey[] = "wifi_pass";
constexpr char kWateringArmedKey[] = "armed";
constexpr char kDoseMsKey[] = "dose_ms";
constexpr char kMaxRunMsKey[] = "max_run_ms";
constexpr char kCooldownMsKey[] = "cooldown_ms";
constexpr char kBootGuardMsKey[] = "boot_guard_ms";
constexpr char kOtaKeyKey[] = "ota_key";
constexpr char kOtaPendingVersionKey[] = "ota_pend_ver";
constexpr char kOtaPendingSourceKey[] = "ota_pend_src";
constexpr char kOtaBootAttemptsKey[] = "ota_boots";
constexpr uint32_t kPairingButtonHoldMs = 3000U;
constexpr uint32_t kPairingWindowMs = 60000U;
constexpr uint32_t kOtaHealthWindowMs = 15000U;
constexpr uint32_t kOtaRestartDelayMs = 750U;
constexpr std::size_t kMaximumOtaFirmwareBytes = 0x140000U;
constexpr std::size_t kOtaHeaderCount = 6U;
const char* kOtaHeaderNames[kOtaHeaderCount] = {
    "X-Tree-Firmware-Target",    "X-Tree-Firmware-Version",
    "X-Tree-Firmware-Size",      "X-Tree-Firmware-SHA256",
    "X-Tree-Firmware-Nonce",     "X-Tree-Firmware-Signature",
};

WebServer server(kHttpPort);
Preferences preferences;
Adafruit_NeoPixel pixel(1U, LED_PIN, NEO_GRB + NEO_KHZ800);
std::unique_ptr<WateringController> controller;
std::array<uint16_t, kMoistureSampleCount> moisture_samples{};
std::size_t moisture_sample_size = 0U;
std::size_t moisture_sample_next = 0U;
uint16_t moisture_median = 0U;
uint32_t last_moisture_sample_at = 0U;
uint32_t last_wifi_attempt_at = 0U;
uint32_t success_led_until = 0U;
uint32_t last_led_color = UINT32_MAX;
wl_status_t previous_wifi_status = WL_NO_SHIELD;
bool preferences_ready = false;
bool network_config_valid = false;
bool watchdog_ready = false;
bool mdns_ready = false;
bool mdns_start_attempted = false;
uint32_t last_mdns_attempt_at = 0U;
esp_timer_handle_t pump_safety_timer = nullptr;
std::atomic<bool> pump_safety_timer_active{false};
PumpSafetyGate pump_safety_gate;
RuntimeConfig runtime_config = watering::fail_closed_runtime_config();
uint32_t pairing_button_pressed_at = 0U;
bool pairing_button_latched = false;
uint32_t pairing_window_until = 0U;
std::string ota_nonce;
uint32_t ota_nonce_issued_at = 0U;
bool ota_update_active = false;
bool ota_reboot_pending = false;
uint32_t ota_restart_at = 0U;
bool ota_boot_validation_pending = false;
bool ota_boot_rollback_failed = false;
uint32_t ota_boot_validation_started_at = 0U;
uint32_t ota_boot_guard_ms = kOtaHealthWindowMs;

struct OtaUploadState {
  OtaMetadata metadata;
  std::size_t received = 0U;
  bool failed = false;
  bool ready_to_finalize = false;
  bool sha_initialized = false;
  std::string error_code;
  std::array<uint8_t, watering::kOtaDigestBytes> digest{};
  mbedtls_sha256_context sha_context{};
};

OtaUploadState ota_upload;

struct ProvisioningLoadResult {
  bool valid;
  watering::ProvisioningAction action;
};

RuntimeConfig compiled_runtime_config() {
  return RuntimeConfig{
      WIFI_SSID,
      WIFI_PASSWORD,
      WATERING_ARMED,
      static_cast<uint32_t>(DOSE_MS),
      static_cast<uint32_t>(MAX_RUN_MS),
      static_cast<uint32_t>(COOLDOWN_MS),
      static_cast<uint32_t>(BOOT_GUARD_MS),
  };
}

watering::ProvisioningRecord read_stored_runtime_config() {
  const bool present = preferences.isKey(kProvisioningRevisionKey);
  return watering::ProvisioningRecord{
      present,
      preferences.getUInt(kProvisioningRevisionKey, 0U),
      RuntimeConfig{
          preferences.getString(kWifiSsidKey, "").c_str(),
          preferences.getString(kWifiPasswordKey, "").c_str(),
          preferences.getBool(kWateringArmedKey, false),
          preferences.getUInt(kDoseMsKey, 0U),
          preferences.getUInt(kMaxRunMsKey, 0U),
          preferences.getUInt(kCooldownMsKey, 0U),
          preferences.getUInt(kBootGuardMsKey, 0U),
      },
  };
}

bool persist_compiled_runtime_config(const RuntimeConfig& config,
                                     uint32_t revision) {
  const bool fields_written =
      preferences.putString(kWifiSsidKey, config.wifi_ssid.c_str()) > 0U &&
      preferences.putString(kWifiPasswordKey, config.wifi_password.c_str()) >
          0U &&
      preferences.putBool(kWateringArmedKey, config.watering_armed) > 0U &&
      preferences.putUInt(kDoseMsKey, config.dose_ms) > 0U &&
      preferences.putUInt(kMaxRunMsKey, config.max_run_ms) > 0U &&
      preferences.putUInt(kCooldownMsKey, config.cooldown_ms) > 0U &&
      preferences.putUInt(kBootGuardMsKey, config.boot_guard_ms) > 0U;
  if (!fields_written) {
    return false;
  }
  return preferences.putUInt(kProvisioningRevisionKey, revision) > 0U;
}

ProvisioningLoadResult load_runtime_config() {
  const watering::ProvisioningRecord stored = read_stored_runtime_config();
  const watering::ProvisioningRecord compiled{
      true,
      static_cast<uint32_t>(PROVISIONING_REVISION),
      compiled_runtime_config(),
  };
  const watering::ProvisioningSelection selection =
      watering::select_runtime_config(stored, compiled);
  if (selection.action == watering::ProvisioningAction::FailClosed) {
    runtime_config = watering::fail_closed_runtime_config();
    return ProvisioningLoadResult{false, selection.action};
  }
  if (selection.action == watering::ProvisioningAction::PersistCompiled &&
      !persist_compiled_runtime_config(selection.config, selection.revision)) {
    runtime_config = watering::fail_closed_runtime_config();
    return ProvisioningLoadResult{false,
                                  watering::ProvisioningAction::FailClosed};
  }
  runtime_config = selection.config;
  return ProvisioningLoadResult{watering::valid_runtime_config(runtime_config),
                                selection.action};
}

ControllerConfig build_controller_config() {
  return ControllerConfig{
      runtime_config.dose_ms,
      runtime_config.max_run_ms,
      runtime_config.cooldown_ms,
      runtime_config.boot_guard_ms,
      runtime_config.watering_armed,
  };
}

void set_led(uint32_t color) {
  if (color == last_led_color) {
    return;
  }
  pixel.setPixelColor(0U, color);
  pixel.show();
  last_led_color = color;
}

void update_led(uint32_t now) {
  if (controller != nullptr && controller->state() == State::Error) {
    set_led(pixel.Color(255U, 0U, 0U));
  } else if (controller != nullptr && controller->state() == State::Watering) {
    set_led(pixel.Color(255U, 120U, 0U));
  } else if (ota_update_active || ota_reboot_pending ||
             watering::bounded_deadline_is_in_future(pairing_window_until,
                                                     now)) {
    set_led(pixel.Color(120U, 0U, 255U));
  } else if (WiFi.status() != WL_CONNECTED) {
    set_led(pixel.Color(0U, 0U, 255U));
  } else if (watering::bounded_deadline_is_in_future(success_led_until, now)) {
    set_led(pixel.Color(0U, 180U, 0U));
  } else {
    set_led(pixel.Color(0U, 0U, 0U));
  }
}

void pump_safety_timer_callback(void*) {
  // Close the gate before touching GPIO so a concurrent loop cannot reassert HIGH.
  pump_safety_gate.cutoff();
  pump_safety_timer_active.store(false);
  gpio_set_level(static_cast<gpio_num_t>(PUMP_PIN), 0U);
}

bool initialize_pump_safety_timer() {
  esp_timer_create_args_t arguments{};
  arguments.callback = pump_safety_timer_callback;
  arguments.dispatch_method = ESP_TIMER_TASK;
  arguments.name = "pump-cutoff";
  return esp_timer_create(&arguments, &pump_safety_timer) == ESP_OK;
}

void disarm_pump_safety_timer() {
  if (pump_safety_timer != nullptr && pump_safety_timer_active.exchange(false)) {
    (void)esp_timer_stop(pump_safety_timer);
  }
}

bool arm_pump_safety_timer(uint32_t cutoff_ms) {
  const uint32_t maximum_cutoff_ms =
      min(runtime_config.max_run_ms, watering::kAbsoluteMaxRunMs);
  if (pump_safety_timer == nullptr || cutoff_ms == 0U ||
      cutoff_ms > maximum_cutoff_ms) {
    return false;
  }
  disarm_pump_safety_timer();
  pump_safety_gate.arm();
  pump_safety_timer_active.store(true);
  const uint64_t cutoff_runtime_us =
      static_cast<uint64_t>(cutoff_ms) * 1000ULL;
  if (esp_timer_start_once(pump_safety_timer, cutoff_runtime_us) != ESP_OK) {
    pump_safety_timer_active.store(false);
    pump_safety_gate.cutoff();
    return false;
  }
  return true;
}

bool renew_pump_safety_timer(uint32_t cutoff_ms) {
  const uint32_t maximum_cutoff_ms =
      min(runtime_config.max_run_ms, watering::kAbsoluteMaxRunMs);
  if (pump_safety_timer == nullptr || cutoff_ms == 0U ||
      cutoff_ms > maximum_cutoff_ms ||
      !pump_safety_timer_active.load() ||
      !pump_safety_gate.allows_output(true)) {
    return false;
  }

  if (esp_timer_stop(pump_safety_timer) != ESP_OK) {
    pump_safety_timer_active.store(false);
    pump_safety_gate.cutoff();
    gpio_set_level(static_cast<gpio_num_t>(PUMP_PIN), 0U);
    return false;
  }
  pump_safety_timer_active.store(false);
  if (!pump_safety_gate.allows_output(true)) {
    pump_safety_gate.cutoff();
    gpio_set_level(static_cast<gpio_num_t>(PUMP_PIN), 0U);
    return false;
  }

  const uint64_t cutoff_runtime_us =
      static_cast<uint64_t>(cutoff_ms) * 1000ULL;
  pump_safety_timer_active.store(true);
  if (esp_timer_start_once(pump_safety_timer, cutoff_runtime_us) != ESP_OK ||
      !pump_safety_gate.allows_output(true)) {
    pump_safety_timer_active.store(false);
    (void)esp_timer_stop(pump_safety_timer);
    pump_safety_gate.cutoff();
    gpio_set_level(static_cast<gpio_num_t>(PUMP_PIN), 0U);
    return false;
  }
  return true;
}

bool pump_output_should_run() {
  return controller != nullptr &&
         pump_safety_gate.allows_output(controller->pump_on());
}

void apply_pump_output() {
  const bool controller_requests_output =
      controller != nullptr && controller->pump_on();
  if (!controller_requests_output) {
    disarm_pump_safety_timer();
  }
  const bool should_run =
      pump_safety_gate.allows_output(controller_requests_output);
  digitalWrite(PUMP_PIN, should_run ? HIGH : LOW);
  // The timer can close the gate between the first check and GPIO write. A
  // second check prevents a stale HIGH from surviving that race.
  if (should_run &&
      !pump_safety_gate.allows_output(controller_requests_output)) {
    digitalWrite(PUMP_PIN, LOW);
  }
}

void send_json(int status, JsonDocument& document) {
  String body;
  body.reserve(512U);
  serializeJson(document, body);
  server.sendHeader("Cache-Control", "no-store");
  server.send(status, "application/json", body);
}

void send_error(int status, const char* code) {
  JsonDocument response;
  response["error"] = code;
  if (controller != nullptr) {
    response["state"] = watering::state_name(controller->state());
  }
  send_json(status, response);
}

bool ota_actuation_blocked() {
  return ota_update_active || ota_reboot_pending ||
         ota_boot_validation_pending;
}

bool ota_safety_gate_is_open() {
  return controller != nullptr &&
         watering::ota_safety_gate_allows(
             controller->state(), digitalRead(PUMP_PIN) == HIGH,
             controller->state() == State::Watering, ota_update_active,
             ota_reboot_pending || ota_boot_validation_pending);
}

void handle_health() {
  JsonDocument response;
  response["ok"] = true;
  response["device"] = DEVICE_NAME;
  response["uptime_ms"] = millis();
  send_json(200, response);
}

void handle_dashboard() {
  server.sendHeader("Cache-Control", "no-store");
  server.sendHeader("Content-Encoding", "gzip");
  server.sendHeader("Content-Security-Policy",
                    "default-src 'self'; style-src 'unsafe-inline'; "
                    "script-src 'unsafe-inline'; connect-src 'self'; "
                    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'none'");
  server.sendHeader("Referrer-Policy", "no-referrer");
  server.sendHeader("X-Content-Type-Options", "nosniff");
  server.sendHeader("X-Frame-Options", "DENY");
  server.send_P(200, PSTR("text/html; charset=utf-8"),
                reinterpret_cast<PGM_P>(watering::kDashboardHtmlGzip),
                watering::kDashboardHtmlGzipLength);
}

void handle_status() {
  const uint32_t now = millis();
  JsonDocument response;
  response["device_type"] = "tree-watering";
  response["api_version"] = 1;
  response["device_name"] = DEVICE_NAME;
  response["state"] = watering::state_name(controller->state());
  response["pump"] = pump_output_should_run();
  response["uptime_ms"] = now;
  response["wifi_rssi"] = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  response["moisture_adc"] = moisture_median;
  response["armed"] = runtime_config.watering_armed;
  response["default_duration_sec"] = runtime_config.dose_ms / 1000U;
  response["max_duration_sec"] =
      min(runtime_config.max_run_ms, watering::kAbsoluteMaxRunMs) / 1000U;
  response["scheduled_ms"] = controller->scheduled_ms();
  response["watering_mode"] =
      watering::watering_mode_name(controller->watering_mode());
  response["hold_lease_ms"] = watering::kHoldLeaseMs;
  response["hold_max_run_ms"] = watering::kHoldMaxRunMs;
  response["hold_lease_remaining_ms"] =
      controller->hold_lease_remaining_ms(now);
  response["last_request_id"] = controller->last_request_id();
  response["remaining_ms"] = controller->remaining_ms(now);
  response["last_runtime_ms"] = controller->last_runtime_ms();
  response["last_stop_reason"] = controller->last_stop_reason();
  response["firmware_version"] = TREE_FIRMWARE_VERSION;
  response["ota_supported"] = true;
  if (controller->state() == State::Error) {
    response["error_reason"] = controller->error_reason();
  }
  send_json(200, response);
}

void handle_water() {
  if (ota_actuation_blocked()) {
    send_error(423, "firmware_update_locked");
    return;
  }
  const String body = server.arg("plain");
  if (body.length() == 0U || body.length() > kMaximumRequestBodyBytes) {
    send_error(body.length() == 0U ? 400 : 413, "invalid_request_body");
    return;
  }

  JsonDocument request;
  const DeserializationError parse_error = deserializeJson(request, body);
  if (parse_error || !request["request_id"].is<const char*>()) {
    send_error(400, "invalid_request_body");
    return;
  }
  const char* request_id = request["request_id"].as<const char*>();
  const JsonObjectConst request_object = request.as<JsonObjectConst>();
  const JsonVariantConst duration_value = request_object["duration_sec"];
  const bool duration_provided = !duration_value.isUnbound();
  const RequestedDuration duration = watering::resolve_requested_duration(
      duration_value, runtime_config.dose_ms, runtime_config.max_run_ms);
  if (!duration.valid) {
    send_error(400, "invalid_duration_sec");
    return;
  }
  const uint32_t now = millis();
  const StartResult result = duration_provided
                                 ? controller->start(request_id, now,
                                                     duration.duration_ms)
                                 : controller->start(request_id, now);
  if (result != StartResult::Accepted) {
    const HttpDecision decision = watering::http_decision(result);
    Serial.printf("water rejected reason=%s\n", decision.code);
    send_error(decision.status, decision.code);
    return;
  }

  // Persistence precedes the physical HIGH transition. If NVS fails, the
  // controller enters ERROR while the actual pump pin is still LOW.
  if (!preferences_ready || preferences.putString(kLastRequestKey, request_id) == 0U) {
    controller->set_error("NVS_WRITE_FAILED", millis());
    apply_pump_output();
    Serial.println("water rejected reason=NVS_WRITE_FAILED");
    send_error(500, "persistence_failed");
    return;
  }

  if (!arm_pump_safety_timer(controller->scheduled_ms())) {
    controller->set_error("SAFETY_TIMER_ARM_FAILED", millis());
    apply_pump_output();
    Serial.println("water rejected reason=SAFETY_TIMER_ARM_FAILED");
    send_error(500, "safety_timer_failed");
    return;
  }
  apply_pump_output();
  JsonDocument response;
  response["accepted"] = true;
  response["request_id"] = request_id;
  response["state"] = watering::state_name(controller->state());
  response["scheduled_ms"] = controller->scheduled_ms();
  Serial.printf("pump started request_id=%s scheduled_ms=%lu\n", request_id,
                static_cast<unsigned long>(controller->scheduled_ms()));
  send_json(202, response);
}

bool parse_hold_request_id(String& request_id) {
  const String body = server.arg("plain");
  if (body.length() == 0U || body.length() > kMaximumRequestBodyBytes) {
    send_error(body.length() == 0U ? 400 : 413, "invalid_request_body");
    return false;
  }

  JsonDocument request;
  const DeserializationError parse_error = deserializeJson(request, body);
  const JsonObjectConst request_object = request.as<JsonObjectConst>();
  if (parse_error || request_object.isNull() || request_object.size() != 1U ||
      !request_object["request_id"].is<const char*>()) {
    send_error(400, "invalid_request_body");
    return false;
  }
  request_id = request_object["request_id"].as<const char*>();
  return true;
}

void handle_hold_start() {
  if (ota_actuation_blocked()) {
    send_error(423, "firmware_update_locked");
    return;
  }
  String request_id;
  if (!parse_hold_request_id(request_id)) {
    return;
  }

  const StartResult result = controller->start_hold(request_id.c_str(), millis());
  if (result != StartResult::Accepted) {
    const HttpDecision decision = watering::http_decision(result);
    Serial.printf("hold start rejected reason=%s\n", decision.code);
    send_error(decision.status, decision.code);
    return;
  }

  if (!preferences_ready ||
      preferences.putString(kLastRequestKey, request_id) == 0U) {
    controller->set_error("NVS_WRITE_FAILED", millis());
    apply_pump_output();
    Serial.println("hold start rejected reason=NVS_WRITE_FAILED");
    send_error(500, "persistence_failed");
    return;
  }
  if (!arm_pump_safety_timer(watering::kHoldLeaseMs)) {
    controller->set_error("SAFETY_TIMER_ARM_FAILED", millis());
    apply_pump_output();
    Serial.println("hold start rejected reason=SAFETY_TIMER_ARM_FAILED");
    send_error(500, "safety_timer_failed");
    return;
  }

  apply_pump_output();
  JsonDocument response;
  response["accepted"] = true;
  response["request_id"] = request_id;
  response["state"] = watering::state_name(controller->state());
  response["watering_mode"] = "HOLD";
  response["lease_ms"] = watering::kHoldLeaseMs;
  response["max_run_ms"] = watering::kHoldMaxRunMs;
  Serial.printf("hold started request_id=%s lease_ms=%lu max_run_ms=%lu\n",
                request_id.c_str(),
                static_cast<unsigned long>(watering::kHoldLeaseMs),
                static_cast<unsigned long>(watering::kHoldMaxRunMs));
  send_json(202, response);
}

void handle_hold_keepalive() {
  if (ota_actuation_blocked()) {
    send_error(423, "firmware_update_locked");
    return;
  }
  String request_id;
  if (!parse_hold_request_id(request_id)) {
    return;
  }

  const uint32_t now = millis();
  const HoldRenewResult result =
      controller->renew_hold(request_id.c_str(), now);
  if (result != HoldRenewResult::Renewed) {
    apply_pump_output();
    const HttpDecision decision = watering::http_decision(result);
    Serial.printf("hold keepalive rejected reason=%s\n", decision.code);
    send_error(decision.status, decision.code);
    return;
  }
  if (!renew_pump_safety_timer(watering::kHoldLeaseMs)) {
    controller->set_error("SAFETY_TIMER_RENEW_FAILED", millis());
    apply_pump_output();
    Serial.println("hold keepalive rejected reason=SAFETY_TIMER_RENEW_FAILED");
    send_error(500, "safety_timer_failed");
    return;
  }

  apply_pump_output();
  JsonDocument response;
  response["renewed"] = true;
  response["request_id"] = request_id;
  response["lease_ms"] = watering::kHoldLeaseMs;
  response["remaining_ms"] = controller->remaining_ms(now);
  send_json(200, response);
}

void handle_stop() {
  controller->stop(millis());
  apply_pump_output();
  success_led_until = millis() + kSuccessLedMs;
  JsonDocument response;
  response["stopped"] = true;
  response["state"] = watering::state_name(controller->state());
  Serial.printf("pump stop requested state=%s\n",
                watering::state_name(controller->state()));
  send_json(200, response);
}

std::size_t firmware_size_limit() {
  return min(static_cast<std::size_t>(ESP.getFreeSketchSpace()),
             kMaximumOtaFirmwareBytes);
}

bool ota_key_is_provisioned() {
  if (!preferences_ready) {
    return false;
  }
  const std::string key = preferences.getString(kOtaKeyKey, "").c_str();
  return watering::is_lower_hex(key, watering::kOtaDigestHexLength);
}

bool pairing_window_is_open(uint32_t now) {
  return watering::bounded_deadline_is_in_future(pairing_window_until, now) &&
         ota_safety_gate_is_open();
}

void consume_ota_nonce() {
  ota_nonce.clear();
  ota_nonce_issued_at = 0U;
}

void handle_firmware_info() {
  const uint32_t now = millis();
  JsonDocument response;
  response["device_type"] = "tree-watering";
  response["api_version"] = 1;
  response["target"] = TREE_FIRMWARE_TARGET;
  response["current_version"] = TREE_FIRMWARE_VERSION;
  response["ota_supported"] = true;
  response["paired"] = ota_key_is_provisioned();
  response["pairing_window_open"] = pairing_window_is_open(now);
  response["max_firmware_bytes"] = firmware_size_limit();
  send_json(200, response);
}

void handle_firmware_pair() {
  const uint32_t now = millis();
  if (!pairing_window_is_open(now) || !ota_safety_gate_is_open()) {
    send_error(423, "pairing_window_closed");
    return;
  }
  std::array<uint8_t, watering::kOtaDigestBytes> key_bytes{};
  esp_fill_random(key_bytes.data(), key_bytes.size());
  const std::string key =
      watering::encode_lower_hex(key_bytes.data(), key_bytes.size());
  if (!preferences_ready ||
      preferences.putString(kOtaKeyKey, key.c_str()) == 0U) {
    send_error(500, "pairing_persistence_failed");
    return;
  }
  consume_ota_nonce();
  pairing_window_until = 0U;
  JsonDocument response;
  response["paired"] = true;
  response["ota_key"] = key.c_str();
  send_json(200, response);
}

void handle_firmware_challenge() {
  const uint32_t now = millis();
  if (!ota_key_is_provisioned()) {
    send_error(403, "not_paired");
    return;
  }
  if (!ota_safety_gate_is_open()) {
    send_error(423, "firmware_update_locked");
    return;
  }
  if (!watering::nonce_is_fresh_and_matching(
          ota_nonce, ota_nonce, ota_nonce_issued_at, now)) {
    std::array<uint8_t, watering::kOtaDigestBytes> nonce_bytes{};
    esp_fill_random(nonce_bytes.data(), nonce_bytes.size());
    ota_nonce =
        watering::encode_lower_hex(nonce_bytes.data(), nonce_bytes.size());
    ota_nonce_issued_at = now;
  }
  JsonDocument response;
  response["nonce"] = ota_nonce.c_str();
  response["expires_in_ms"] =
      watering::kOtaNonceValidityMs - (now - ota_nonce_issued_at);
  send_json(200, response);
}

const char* ota_metadata_error_code(OtaMetadataError error) {
  switch (error) {
    case OtaMetadataError::InvalidTarget:
      return "invalid_target";
    case OtaMetadataError::InvalidVersion:
      return "invalid_version";
    case OtaMetadataError::InvalidSize:
      return "invalid_size";
    case OtaMetadataError::InvalidSha256:
      return "invalid_sha256";
    case OtaMetadataError::InvalidNonce:
      return "invalid_nonce";
    case OtaMetadataError::InvalidSignature:
      return "invalid_signature";
    case OtaMetadataError::None:
      return "none";
  }
  return "invalid_metadata";
}

OtaMetadata read_ota_metadata() {
  std::size_t size = 0U;
  (void)watering::parse_canonical_size(
      server.header("X-Tree-Firmware-Size").c_str(), size);
  return OtaMetadata{
      server.header("X-Tree-Firmware-Target").c_str(),
      server.header("X-Tree-Firmware-Version").c_str(),
      size,
      server.header("X-Tree-Firmware-SHA256").c_str(),
      server.header("X-Tree-Firmware-Nonce").c_str(),
      server.header("X-Tree-Firmware-Signature").c_str(),
  };
}

bool verify_ota_signature(const OtaMetadata& metadata) {
  const std::string key_hex = preferences.getString(kOtaKeyKey, "").c_str();
  std::array<uint8_t, watering::kOtaDigestBytes> key{};
  std::array<uint8_t, watering::kOtaDigestBytes> expected{};
  std::array<uint8_t, watering::kOtaDigestBytes> actual{};
  if (!watering::decode_lower_hex(key_hex, key.data(), key.size()) ||
      !watering::decode_lower_hex(metadata.signature, expected.data(),
                                  expected.size())) {
    return false;
  }
  const std::string message = watering::ota_canonical_message(
      DEVICE_NAME, metadata.target, TREE_FIRMWARE_VERSION,
      metadata.new_version, metadata.size, metadata.sha256, metadata.nonce);
  const mbedtls_md_info_t* md_info =
      mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (md_info == nullptr ||
      mbedtls_md_hmac(md_info, key.data(), key.size(),
                      reinterpret_cast<const unsigned char*>(message.data()),
                      message.size(), actual.data()) != 0) {
    return false;
  }
  return watering::constant_time_bytes_equal(expected.data(), actual.data(),
                                              expected.size());
}

void reset_ota_upload_state() {
  if (ota_upload.sha_initialized) {
    mbedtls_sha256_free(&ota_upload.sha_context);
  }
  ota_upload = OtaUploadState{};
}

void abort_ota_upload(const char* error_code) {
  if (Update.isRunning()) {
    Update.abort();
  }
  if (ota_upload.sha_initialized) {
    mbedtls_sha256_free(&ota_upload.sha_context);
    ota_upload.sha_initialized = false;
  }
  ota_update_active = false;
  ota_upload.failed = true;
  ota_upload.ready_to_finalize = false;
  ota_upload.error_code = error_code == nullptr ? "update_failed" : error_code;
  pump_safety_gate.cutoff();
  disarm_pump_safety_timer();
  digitalWrite(PUMP_PIN, LOW);
}

bool write_pending_update_marker(const std::string& target_version) {
  return preferences_ready &&
         preferences.putString(kOtaPendingVersionKey,
                               target_version.c_str()) > 0U &&
         preferences.putString(kOtaPendingSourceKey,
                               TREE_FIRMWARE_VERSION) > 0U &&
         preferences.putUChar(kOtaBootAttemptsKey, 0U) > 0U;
}

void clear_pending_update_marker() {
  if (!preferences_ready) {
    return;
  }
  preferences.remove(kOtaPendingVersionKey);
  preferences.remove(kOtaPendingSourceKey);
  preferences.remove(kOtaBootAttemptsKey);
}

void inspect_pending_update_marker() {
  if (!preferences_ready) {
    return;
  }
  const String target = preferences.getString(kOtaPendingVersionKey, "");
  if (target.isEmpty()) {
    return;
  }
  if (target != TREE_FIRMWARE_VERSION) {
    clear_pending_update_marker();
    return;
  }
  const uint8_t attempts = preferences.getUChar(kOtaBootAttemptsKey, 0U);
  if (attempts >= 1U) {
    pump_safety_gate.cutoff();
    digitalWrite(PUMP_PIN, LOW);
    if (Update.canRollBack() && Update.rollBack()) {
      ESP.restart();
    }
    ota_boot_rollback_failed = true;
    return;
  }
  if (preferences.putUChar(kOtaBootAttemptsKey, 1U) == 0U) {
    ota_boot_rollback_failed = true;
    return;
  }
  ota_boot_guard_ms = kOtaHealthWindowMs;
  ota_boot_validation_started_at = millis();
  ota_boot_validation_pending = true;
}

bool begin_ota_upload(HTTPUpload& upload) {
  reset_ota_upload_state();
  if (upload.name != "firmware" || !preferences_ready) {
    abort_ota_upload("invalid_upload_field");
    return false;
  }
  const OtaMetadata metadata = read_ota_metadata();
  const OtaMetadataError metadata_error = watering::validate_ota_metadata(
      metadata, TREE_FIRMWARE_TARGET, TREE_FIRMWARE_VERSION,
      firmware_size_limit());
  if (metadata_error != OtaMetadataError::None) {
    abort_ota_upload(ota_metadata_error_code(metadata_error));
    return false;
  }
  if (!watering::nonce_is_fresh_and_matching(
          ota_nonce, metadata.nonce, ota_nonce_issued_at, millis())) {
    abort_ota_upload("invalid_nonce");
    return false;
  }
  if (!ota_safety_gate_is_open()) {
    abort_ota_upload("firmware_update_locked");
    return false;
  }
  if (!verify_ota_signature(metadata)) {
    abort_ota_upload("invalid_signature");
    return false;
  }
  consume_ota_nonce();
  pump_safety_gate.cutoff();
  disarm_pump_safety_timer();
  digitalWrite(PUMP_PIN, LOW);
  if (digitalRead(PUMP_PIN) == HIGH ||
      !Update.begin(metadata.size, U_FLASH)) {
    abort_ota_upload("update_begin_failed");
    return false;
  }
  ota_upload.metadata = metadata;
  mbedtls_sha256_init(&ota_upload.sha_context);
  ota_upload.sha_initialized = true;
  if (mbedtls_sha256_starts_ret(&ota_upload.sha_context, 0) != 0) {
    abort_ota_upload("sha256_init_failed");
    return false;
  }
  ota_update_active = true;
  return true;
}

void handle_firmware_upload() {
  HTTPUpload& upload = server.upload();
  if (upload.status == UPLOAD_FILE_START) {
    (void)begin_ota_upload(upload);
    return;
  }
  if (upload.status == UPLOAD_FILE_ABORTED) {
    abort_ota_upload("upload_aborted");
    return;
  }
  if (ota_upload.failed || !ota_update_active) {
    return;
  }
  if (upload.status == UPLOAD_FILE_WRITE) {
    if (ota_upload.received + upload.currentSize > ota_upload.metadata.size ||
        Update.write(upload.buf, upload.currentSize) != upload.currentSize ||
        mbedtls_sha256_update_ret(&ota_upload.sha_context, upload.buf,
                                  upload.currentSize) != 0) {
      abort_ota_upload("upload_write_failed");
      return;
    }
    ota_upload.received += upload.currentSize;
    if (watchdog_ready) {
      esp_task_wdt_reset();
    }
    return;
  }
  if (upload.status != UPLOAD_FILE_END ||
      ota_upload.received != ota_upload.metadata.size ||
      mbedtls_sha256_finish_ret(&ota_upload.sha_context,
                                ota_upload.digest.data()) != 0) {
    abort_ota_upload("upload_size_or_hash_failed");
    return;
  }
  mbedtls_sha256_free(&ota_upload.sha_context);
  ota_upload.sha_initialized = false;
  std::array<uint8_t, watering::kOtaDigestBytes> expected{};
  if (!watering::decode_lower_hex(ota_upload.metadata.sha256, expected.data(),
                                  expected.size()) ||
      !watering::constant_time_bytes_equal(expected.data(),
                                            ota_upload.digest.data(),
                                            expected.size())) {
    abort_ota_upload("firmware_hash_mismatch");
    return;
  }
  ota_upload.ready_to_finalize = true;
}

void finalize_firmware_update() {
  if (ota_upload.failed || !ota_upload.ready_to_finalize ||
      !ota_update_active) {
    send_error(400, ota_upload.error_code.empty()
                        ? "firmware_upload_incomplete"
                        : ota_upload.error_code.c_str());
    return;
  }
  if (!write_pending_update_marker(ota_upload.metadata.new_version)) {
    abort_ota_upload("pending_marker_failed");
    send_error(500, "pending_marker_failed");
    return;
  }
  if (!Update.end(false)) {
    clear_pending_update_marker();
    abort_ota_upload("update_finalize_failed");
    send_error(500, "update_finalize_failed");
    return;
  }
  ota_update_active = false;
  ota_reboot_pending = true;
  ota_restart_at = millis() + kOtaRestartDelayMs;
  JsonDocument response;
  response["accepted"] = true;
  response["firmware_version"] = ota_upload.metadata.new_version.c_str();
  response["restarting"] = true;
  send_json(202, response);
}

void configure_http_server() {
  server.on("/", HTTP_GET, handle_dashboard);
  server.on("/healthz", HTTP_GET, handle_health);
  server.on("/v1/status", HTTP_GET, handle_status);
  server.on("/v1/water", HTTP_POST, handle_water);
  server.on("/v1/hold/start", HTTP_POST, handle_hold_start);
  server.on("/v1/hold/keepalive", HTTP_POST, handle_hold_keepalive);
  server.on("/v1/stop", HTTP_POST, handle_stop);
  server.on("/v1/firmware", HTTP_GET, handle_firmware_info);
  server.on("/v1/firmware/pair", HTTP_POST, handle_firmware_pair);
  server.on("/v1/firmware/challenge", HTTP_POST,
            handle_firmware_challenge);
  server.on("/v1/firmware/update", HTTP_POST,
            finalize_firmware_update, handle_firmware_upload);
  server.collectHeaders(kOtaHeaderNames, kOtaHeaderCount);
  server.onNotFound([]() { send_error(404, "not_found"); });
  server.begin();
  Serial.println("HTTP server started");
}

void maintain_pairing_button(uint32_t now) {
  if (!watering::bounded_deadline_is_in_future(pairing_window_until, now)) {
    pairing_window_until = 0U;
  }
  const bool pressed = digitalRead(ATOM_BUTTON_PIN) == LOW;
  if (!pressed) {
    pairing_button_pressed_at = 0U;
    pairing_button_latched = false;
    return;
  }
  if (pairing_button_pressed_at == 0U) {
    pairing_button_pressed_at = now;
    return;
  }
  if (!pairing_button_latched &&
      now - pairing_button_pressed_at >= kPairingButtonHoldMs &&
      ota_safety_gate_is_open()) {
    pairing_window_until = now + kPairingWindowMs;
    pairing_button_latched = true;
  }
}

void maintain_ota_boot_validation(uint32_t now) {
  const watering::OtaBootValidationDecision decision =
      watering::ota_boot_validation_decision(
          ota_boot_validation_pending, ota_boot_validation_started_at, now,
          ota_boot_guard_ms, WiFi.status() == WL_CONNECTED, watchdog_ready,
          controller == nullptr ? State::Error : controller->state(),
          digitalRead(PUMP_PIN) == HIGH);
  if (decision == watering::OtaBootValidationDecision::Wait) {
    return;
  }
  if (decision == watering::OtaBootValidationDecision::Confirm) {
    clear_pending_update_marker();
    ota_boot_validation_pending = false;
    return;
  }

  pump_safety_gate.cutoff();
  disarm_pump_safety_timer();
  digitalWrite(PUMP_PIN, LOW);
  if (Update.canRollBack() && Update.rollBack()) {
    ESP.restart();
  }
  ota_boot_validation_pending = false;
  ota_boot_rollback_failed = true;
  if (controller != nullptr) {
    controller->set_error("OTA_ROLLBACK_FAILED", now);
  }
}

void maintain_ota_restart(uint32_t now) {
  if (!ota_reboot_pending ||
      watering::bounded_deadline_is_in_future(ota_restart_at, now)) {
    return;
  }
  pump_safety_gate.cutoff();
  disarm_pump_safety_timer();
  digitalWrite(PUMP_PIN, LOW);
  ESP.restart();
}

void sample_moisture(uint32_t now) {
  if (moisture_sample_size > 0U &&
      now - last_moisture_sample_at < MOISTURE_SAMPLE_INTERVAL_MS) {
    return;
  }
  last_moisture_sample_at = now;
  moisture_samples[moisture_sample_next] =
      static_cast<uint16_t>(analogRead(MOISTURE_PIN));
  moisture_sample_next =
      (moisture_sample_next + 1U) % kMoistureSampleCount;
  moisture_sample_size =
      min(moisture_sample_size + 1U, kMoistureSampleCount);
  moisture_median =
      watering::median_u16(moisture_samples.data(), moisture_sample_size);
}

void stop_discovery_service() {
  if (!mdns_ready) {
    mdns_start_attempted = false;
    return;
  }
  MDNS.end();
  mdns_ready = false;
  mdns_start_attempted = false;
  Serial.println("mDNS discovery stopped");
}

void start_discovery_service() {
  if (mdns_ready || WiFi.status() != WL_CONNECTED) {
    return;
  }
  const uint32_t now = millis();
  if (mdns_start_attempted &&
      now - last_mdns_attempt_at < kMDNSRetryIntervalMs) {
    return;
  }
  mdns_start_attempted = true;
  last_mdns_attempt_at = now;
  if (!MDNS.begin(DEVICE_NAME)) {
    Serial.println("mDNS discovery failed to start");
    return;
  }
  MDNS.setInstanceName(DEVICE_NAME);
  MDNS.addService("tree-watering", "tcp", kHttpPort);
  MDNS.addServiceTxt(kDiscoveryServiceType, "tcp", "device_type",
                     "tree-watering");
  MDNS.addServiceTxt(kDiscoveryServiceType, "tcp", "api_version", "1");
  MDNS.addServiceTxt(kDiscoveryServiceType, "tcp", "device_name", DEVICE_NAME);
  mdns_ready = true;
  Serial.printf("mDNS discovery ready host=%s.local service=_%s._tcp\n",
                DEVICE_NAME, kDiscoveryServiceType);
}

void maintain_wifi(uint32_t now) {
  if (!network_config_valid) {
    return;
  }
  const wl_status_t current = WiFi.status();
  if (current != previous_wifi_status) {
    if (current == WL_CONNECTED) {
      Serial.printf("Wi-Fi connected ip=%s rssi=%d\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      success_led_until = now + kSuccessLedMs;
      start_discovery_service();
    } else {
      stop_discovery_service();
      Serial.printf("Wi-Fi state=%d\n", static_cast<int>(current));
    }
    previous_wifi_status = current;
  }
  if (current == WL_CONNECTED && !mdns_ready) {
    start_discovery_service();
  }
  if (current != WL_CONNECTED &&
      now - last_wifi_attempt_at >= WIFI_RECONNECT_INTERVAL_MS) {
    last_wifi_attempt_at = now;
    WiFi.disconnect(false, false);
    WiFi.begin(runtime_config.wifi_ssid.c_str(),
               runtime_config.wifi_password.c_str());
    Serial.println("Wi-Fi reconnect requested");
  }
}

void connect_wifi_initially() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_NAME);
  WiFi.setAutoReconnect(true);
  WiFi.begin(runtime_config.wifi_ssid.c_str(),
             runtime_config.wifi_password.c_str());
  last_wifi_attempt_at = millis();
  const uint32_t started_at = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - started_at < WIFI_CONNECT_TIMEOUT_MS) {
    controller->tick(millis());
    apply_pump_output();
    update_led(millis());
    delay(50U);
  }
  previous_wifi_status = WiFi.status();
  if (previous_wifi_status == WL_CONNECTED) {
    Serial.printf("Wi-Fi connected ip=%s rssi=%d\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    success_led_until = millis() + kSuccessLedMs;
  } else {
    Serial.println("Wi-Fi initial connection timed out; running offline");
  }
}

}  // namespace

void setup() {
  // This must remain the first hardware action. Do not move Wi-Fi, serial, NVS,
  // LED, or sensor setup above the explicit pump-off sequence.
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);
  const bool pump_safety_timer_ready = initialize_pump_safety_timer();

  Serial.begin(115200);
  delay(20U);
  Serial.printf("boot firmware=%s reset_reason=%d\n", TREE_FIRMWARE_VERSION,
                static_cast<int>(esp_reset_reason()));

  pixel.begin();
  pixel.setBrightness(kLedBrightness);
  set_led(pixel.Color(0U, 0U, 255U));
  pinMode(MOISTURE_PIN, INPUT);
  pinMode(ATOM_BUTTON_PIN, INPUT);

  preferences_ready = preferences.begin(kPreferencesNamespace, false);
  String restored_request_id;
  ProvisioningLoadResult provisioning{
      false, watering::ProvisioningAction::FailClosed};
  if (preferences_ready) {
    restored_request_id = preferences.getString(kLastRequestKey, "");
    provisioning = load_runtime_config();
    inspect_pending_update_marker();
  }

  controller.reset(new WateringController(
      build_controller_config(), millis(), restored_request_id.c_str()));
  network_config_valid = provisioning.valid;
  if (!pump_safety_timer_ready) {
    controller->set_error("SAFETY_TIMER_INIT_FAILED", millis());
  } else if (!preferences_ready) {
    controller->set_error("NVS_OPEN_FAILED", millis());
  } else if (!network_config_valid) {
    controller->set_error("INVALID_RUNTIME_CONFIG", millis());
  } else if (ota_boot_rollback_failed) {
    controller->set_error("OTA_ROLLBACK_FAILED", millis());
  }
  apply_pump_output();

  if (network_config_valid) {
    connect_wifi_initially();
    configure_http_server();
    start_discovery_service();
  } else {
    Serial.println("Wi-Fi disabled because configuration is invalid");
  }
  sample_moisture(millis());

  const esp_err_t watchdog_init =
      esp_task_wdt_init(WATCHDOG_TIMEOUT_SEC, true);
  if (watchdog_init == ESP_OK || watchdog_init == ESP_ERR_INVALID_STATE) {
    const esp_err_t watchdog_add = esp_task_wdt_add(nullptr);
    watchdog_ready =
        watchdog_add == ESP_OK || watchdog_add == ESP_ERR_INVALID_ARG;
    if (!watchdog_ready) {
      controller->set_error("WATCHDOG_SUBSCRIBE_FAILED", millis());
      apply_pump_output();
    }
  } else {
    controller->set_error("WATCHDOG_INIT_FAILED", millis());
    apply_pump_output();
  }
  Serial.printf("boot state=%s armed=%s\n",
                watering::state_name(controller->state()),
                runtime_config.watering_armed ? "true" : "false");
}

void loop() {
  if (watchdog_ready) {
    esp_task_wdt_reset();
  }
  uint32_t now = millis();
  controller->tick(now);
  apply_pump_output();
  maintain_pairing_button(now);
  maintain_ota_boot_validation(now);
  maintain_ota_restart(now);
  maintain_wifi(now);
  sample_moisture(now);
  update_led(now);

  if (network_config_valid) {
    server.handleClient();
  }

  // Re-check after handling a request so stop/timer outputs are applied in the
  // same loop iteration even if the request handler consumed measurable time.
  now = millis();
  controller->tick(now);
  apply_pump_output();
  maintain_pairing_button(now);
  maintain_ota_boot_validation(now);
  maintain_ota_restart(now);
  update_led(now);
  if (watchdog_ready) {
    esp_task_wdt_reset();
  }
  delay(2U);
}
