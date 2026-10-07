#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <math.h>
#include <sys/time.h>
#include <time.h>

// Wokwi online can reach this public broker. Keep the Python MQTT_HOST in sync.
constexpr char WIFI_SSID[] = "Wokwi-GUEST";
constexpr char MQTT_HOST[] = "broker.hivemq.com";
constexpr uint16_t MQTT_PORT = 1883;
constexpr char MQTT_TOPIC[] = "iot/B23DCAT237/esp32/pir/telemetry";
constexpr char DEVICE_ID[] = "ESP32-PIR-B23DCAT237";
constexpr char LOCATION[] = "lab_ptit";
constexpr uint8_t DHT_PIN = 15;
constexpr uint8_t PIR_PIN = 27;
constexpr uint8_t LED_PIN = 2;
constexpr unsigned long PUBLISH_INTERVAL_MS = 5000;

DHT dht(DHT_PIN, DHT22);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
unsigned long lastPublish = 0;
unsigned long lastWifiAttempt = 0;
unsigned long lastMqttAttempt = 0;
uint32_t sequenceNumber = 0;
bool lastPublishedMotion = false;

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED || millis() - lastWifiAttempt < 5000) return;
  lastWifiAttempt = millis();
  Serial.println("[WiFi] Connecting...");
  WiFi.begin(WIFI_SSID, "", 6);
}

void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected() || millis() - lastMqttAttempt < 5000) return;
  lastMqttAttempt = millis();
  String clientId = String("bai2-") + String((uint32_t)ESP.getEfuseMac(), HEX);
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("[MQTT] Connected");
  } else {
    Serial.printf("[MQTT] Connection failed: %d\n", mqtt.state());
  }
}

bool publishTelemetry(bool motion) {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("[DHT22] Sensor read failed");
    return false;
  }

  struct timeval now;
  gettimeofday(&now, nullptr);
  uint64_t sentAtMs = now.tv_sec > 1577836800 ?
    (uint64_t)now.tv_sec * 1000ULL + now.tv_usec / 1000 : 0;

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["location"] = LOCATION;
  doc["temperature"] = roundf(temperature * 100) / 100;
  doc["humidity"] = roundf(humidity * 100) / 100;
  doc["motion"] = motion ? 1 : 0;
  doc["rssi"] = WiFi.RSSI();
  doc["sequence"] = sequenceNumber + 1;
  doc["uptime_s"] = millis() / 1000;
  doc["sent_at_ms"] = sentAtMs;
  char payload[384];
  size_t length = serializeJson(doc, payload, sizeof(payload));
  if (length == 0 || length >= sizeof(payload)) {
    Serial.println("[MQTT] JSON buffer too small");
    return false;
  }
  Serial.println(payload);
  if (mqtt.publish(MQTT_TOPIC, payload)) {
    sequenceNumber++;
    Serial.println("[MQTT] Published");
    return true;
  } else {
    Serial.println("[MQTT] Publish failed");
    return false;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(PIR_PIN, INPUT);
  dht.begin();
  WiFi.mode(WIFI_STA);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  // Make the first Wi-Fi attempt immediate despite millis() initially being zero.
  lastWifiAttempt = millis() - 5000;
  lastMqttAttempt = millis() - 5000;
  connectWifi();
}

void loop() {
  bool motion = digitalRead(PIR_PIN) == HIGH;
  digitalWrite(LED_PIN, motion ? HIGH : LOW);
  connectWifi();
  connectMqtt();
  mqtt.loop();
  if (mqtt.connected() && (motion != lastPublishedMotion || millis() - lastPublish >= PUBLISH_INTERVAL_MS)) {
    lastPublish = millis();
    if (publishTelemetry(motion)) lastPublishedMotion = motion;
  }
  delay(20);
}
