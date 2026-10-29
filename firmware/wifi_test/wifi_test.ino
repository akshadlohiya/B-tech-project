// Wi-Fi path test: ESP32 only, no DW1000 needed.
//
// Pretends to be tag T1 walking a 1.5 m circle inside three anchors (A1, A2, A3).
// Sends the same UDP/JSON packets as uwb_tag, so the hotspot -> Pi gateway -> viewer
// chain can be proven before any radio is wired. In the viewer's map, put
// A1 (-3, 2.4, -3), A2 (3, 2.4, -3), A3 (0, 2.4, 3) and tag T1.

#include <WiFi.h>
#include <WiFiUdp.h>
#include <math.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

#define LED_PIN 2   // Built-in blue LED on most ESP32 DevKits

WiFiUDP udp;
const int UDP_PORT = 9000;

// Anchor positions matching the map: A1=(-3, 2.4, -3), A2=(3, 2.4, -3), A3=(0, 2.4, 3)
const float ANCHORS[3][3] = {
  {-3.0f, 2.4f, -3.0f},
  { 3.0f, 2.4f, -3.0f},
  { 0.0f, 2.4f,  3.0f}
};
const char* ANCHOR_IDS[3] = {"A1", "A2", "A3"};

float angle = 0.0f;
const float RADIUS = 1.5f;
const float TAG_Y = 1.0f;

void connectWiFi() {
  Serial.printf("\nConnecting to Wi-Fi SSID '%s'...", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  connectWiFi();
  udp.begin(UDP_PORT);
  Serial.println("wifi_test running: simulating T1 circling at 1.5m radius...");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // T1 circular trajectory in x-z plane
  float tx = RADIUS * cos(angle);
  float ty = TAG_Y;
  float tz = RADIUS * sin(angle);
  angle += 0.1f;
  if (angle > 2.0f * M_PI) angle -= 2.0f * M_PI;

  IPAddress target;
#ifdef PI_IP
  target.fromString(PI_IP);
#else
  target = WiFi.broadcastIP();
#endif

  digitalWrite(LED_PIN, HIGH);

  // Send fake range reading for each anchor A1, A2, A3
  for (int i = 0; i < 3; i++) {
    float dx = tx - ANCHORS[i][0];
    float dy = ty - ANCHORS[i][1];
    float dz = tz - ANCHORS[i][2];
    float dist = sqrt(dx*dx + dy*dy + dz*dz);

    char buf[128];
    snprintf(buf, sizeof(buf),
             "{\"tag\":\"T1\",\"anchor\":\"%s\",\"range\":%.2f,\"rxPower\":-80.0,\"fpPower\":-83.0}",
             ANCHOR_IDS[i], dist);

    udp.beginPacket(target, UDP_PORT);
    udp.write((const uint8_t*)buf, strlen(buf));
    udp.endPacket();

    Serial.printf("[TX] -> %s: %s\n", target.toString().c_str(), buf);
    delay(20);
  }

  digitalWrite(LED_PIN, LOW);
  delay(140); // ~5 Hz update cycle
}
