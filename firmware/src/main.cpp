#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>

#include <atomic>
#include <array>
#include <memory>

#include "api_contract.h"
#include "config.h"
#include "dashboard_page.generated.h"
#include "pump_safety_gate.h"
#include "sensor_filter.h"
#include "watering_controller.h"

namespace {

using watering::ControllerConfig;
using watering::HoldRenewResult;
using watering::HttpDecision;
using watering::PumpSafetyGate;
using watering::RequestedDuration;
using watering::StartResult;
using watering::State;
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

bool deadline_in_future(uint32_t deadline, uint32_t now) {
  return static_cast<int32_t>(deadline - now) > 0;
}

bool has_placeholder(const char* value) {
  if (value == nullptr) {
    return true;
  }
  String text(value);
  text.toUpperCase();
  return text.isEmpty() || text.indexOf("CHANGE_ME") >= 0 ||
         text.indexOf("REPLACE_ME") >= 0;
}

bool wifi_config_valid() {
  return !has_placeholder(WIFI_SSID) && !has_placeholder(WIFI_PASSWORD);
}

ControllerConfig build_controller_config() {
  return ControllerConfig{
      static_cast<uint32_t>(DOSE_MS),
      static_cast<uint32_t>(MAX_RUN_MS),
      static_cast<uint32_t>(COOLDOWN_MS),
      static_cast<uint32_t>(BOOT_GUARD_MS),
      WATERING_ARMED,
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
  } else if (WiFi.status() != WL_CONNECTED) {
    set_led(pixel.Color(0U, 0U, 255U));
  } else if (deadline_in_future(success_led_until, now)) {
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
      min(static_cast<uint32_t>(MAX_RUN_MS), watering::kAbsoluteMaxRunMs);
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
      min(static_cast<uint32_t>(MAX_RUN_MS), watering::kAbsoluteMaxRunMs);
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
  response["armed"] = WATERING_ARMED;
  response["default_duration_sec"] = static_cast<uint32_t>(DOSE_MS) / 1000U;
  response["max_duration_sec"] =
      min(static_cast<uint32_t>(MAX_RUN_MS), watering::kAbsoluteMaxRunMs) /
      1000U;
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
  response["firmware_version"] = FIRMWARE_VERSION;
  if (controller->state() == State::Error) {
    response["error_reason"] = controller->error_reason();
  }
  send_json(200, response);
}

void handle_water() {
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
      duration_value, static_cast<uint32_t>(DOSE_MS),
      static_cast<uint32_t>(MAX_RUN_MS));
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

void configure_http_server() {
  server.on("/", HTTP_GET, handle_dashboard);
  server.on("/healthz", HTTP_GET, handle_health);
  server.on("/v1/status", HTTP_GET, handle_status);
  server.on("/v1/water", HTTP_POST, handle_water);
  server.on("/v1/hold/start", HTTP_POST, handle_hold_start);
  server.on("/v1/hold/keepalive", HTTP_POST, handle_hold_keepalive);
  server.on("/v1/stop", HTTP_POST, handle_stop);
  server.onNotFound([]() { send_error(404, "not_found"); });
  server.begin();
  Serial.println("HTTP server started");
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
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("Wi-Fi reconnect requested");
  }
}

void connect_wifi_initially() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(DEVICE_NAME);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
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
  Serial.printf("boot firmware=%s reset_reason=%d\n", FIRMWARE_VERSION,
                static_cast<int>(esp_reset_reason()));

  pixel.begin();
  pixel.setBrightness(kLedBrightness);
  set_led(pixel.Color(0U, 0U, 255U));
  pinMode(MOISTURE_PIN, INPUT);

  preferences_ready = preferences.begin(kPreferencesNamespace, false);
  String restored_request_id;
  if (preferences_ready) {
    restored_request_id = preferences.getString(kLastRequestKey, "");
  }

  controller.reset(new WateringController(
      build_controller_config(), millis(), restored_request_id.c_str()));
  network_config_valid = wifi_config_valid();
  if (!pump_safety_timer_ready) {
    controller->set_error("SAFETY_TIMER_INIT_FAILED", millis());
  } else if (!preferences_ready) {
    controller->set_error("NVS_OPEN_FAILED", millis());
  } else if (!network_config_valid) {
    controller->set_error("INVALID_WIFI_CONFIG", millis());
  }
  apply_pump_output();

  if (network_config_valid) {
    connect_wifi_initially();
  } else {
    Serial.println("Wi-Fi disabled because configuration is invalid");
  }
  configure_http_server();
  start_discovery_service();
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
                WATERING_ARMED ? "true" : "false");
}

void loop() {
  if (watchdog_ready) {
    esp_task_wdt_reset();
  }
  uint32_t now = millis();
  controller->tick(now);
  apply_pump_output();
  maintain_wifi(now);
  sample_moisture(now);
  update_led(now);

  server.handleClient();

  // Re-check after handling a request so stop/timer outputs are applied in the
  // same loop iteration even if the request handler consumed measurable time.
  now = millis();
  controller->tick(now);
  apply_pump_output();
  update_led(now);
  if (watchdog_ready) {
    esp_task_wdt_reset();
  }
  delay(2U);
}
