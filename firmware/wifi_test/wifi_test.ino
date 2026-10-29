// Wi-Fi path test: ESP32 only, no DW1000 needed.
//
// Pretends to be tag T1 walking a 1.5 m circle inside three anchors and sends
// the same UDP/JSON packets as uwb_tag, so the hotspot -> Pi gateway -> viewer
// chain can be proven before any radio is wired. In the viewer's map, put
// A1, A2, A3 at the ANCHORS positions below and add tag T1.

#include <WiFi.h>
#include <WiFiUdp.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.example.h to secrets.h and fill in your hotspot SSID and password"
#endif

#define UDP_PORT  9000
#define LED_PIN   2            // onboard blue LED on most DevKits

struct Anchor { const char *id; float x, y, z; };
const Anchor ANCHORS[] = {     // metres: x = east, y = height, z = north
  {"A1", -3.0, 2.4, -3.0},
  {"A2",  3.0, 2.4, -3.0},
  {"A3",  0.0, 2.4,  3.0},
};
const float TAG_H = 0.6;       // matches the map's default assumedTagHeightM
const float RADIUS_M = 1.5;
const float LAP_S = 20.0;      // one circle every 20 s
const uint32_t CYCLE_MS = 200; // 5 Hz, the map's default updateRateHz

WiFiUDP udp;
IPAddress target;

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[test] connecting to %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
#ifdef PI_IP
  target.fromString(PI_IP);
#else
  target = WiFi.broadcastIP();
#endif
  Serial.printf("\n[test] ip %s -> sending to %s:%d\n",
                WiFi.localIP().toString().c_str(), target.toString().c_str(), UDP_PORT);
}

void loop() {
  float a = 2 * PI * (millis() / 1000.0f) / LAP_S;
  float tx = RADIUS_M * cosf(a), tz = RADIUS_M * sinf(a);

  digitalWrite(LED_PIN, HIGH);
  for (const Anchor &an : ANCHORS) {
    float dx = tx - an.x, dy = TAG_H - an.y, dz = tz - an.z;
    float range = sqrtf(dx * dx + dy * dy + dz * dz) + random(-50, 51) / 1000.0f;   // +-5 cm noise
    char pkt[128];
    snprintf(pkt, sizeof pkt,
             "{\"tag\":\"T1\",\"anchor\":\"%s\",\"range\":%.3f,\"rxPower\":-80.0,\"fpPower\":-83.0}",
             an.id, range);
    udp.beginPacket(target, UDP_PORT);
    udp.write((const uint8_t *)pkt, strlen(pkt));
    udp.endPacket();
    Serial.println(pkt);
    delay(10);                 // real anchors answer one after another
  }
  digitalWrite(LED_PIN, LOW);

  if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
  delay(CYCLE_MS - 3 * 10);
}
