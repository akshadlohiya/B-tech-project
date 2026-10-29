// UWB tag node: ESP32 + DW1000, the device being tracked.
//
// Ranges to anchors A1..A3 (DS-TWR) and sends each range to the Pi gateway as
// one UDP/JSON datagram on port 9000, the format anchor-source/hardware_source.py
// parses:
//   {"tag":"T1","anchor":"A1","range":2.41,"rxPower":-83.2,"fpPower":-86.1}
// It follows the gateway's beacon, so the Pi's hotspot IP can change without
// reflashing; see checkBeacon().
//
// Library: jremington/UWB-Indoor-Localization_Arduino (DW1000_library).

#include <SPI.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "DW1000Ranging.h"
#include "DW1000.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.example.h to secrets.h and fill in your hotspot SSID and password"
#endif

#define TAG_ID    "T1"         // must match the tag id in the viewer's map
#define UDP_PORT  9000         // gateway's UWB_UDP_PORT
#define BEACON_PORT 9001       // gateway announces itself here
#define MAX_RANGE_M 50.0f      // drop obviously bad ranges

// ---- wiring (same on every node) -------------------------------------------
#define SPI_SCK  18
#define SPI_MISO 19
#define SPI_MOSI 23
#define DW_CS    4
#define PIN_RST  27
#define PIN_IRQ  34

char tag_addr[] = "7D:00:22:EA:82:60:3B:9C";

#define LOG_PREFIX "[T1]"

WiFiUDP udp;
IPAddress target;
WiFiUDP beacon;

// Where packets go. The gateway beacons {"rtls":"gateway","port":9000} to port 9001 every 2 s
// and we send to whoever beacons, so the Pi's hotspot IP can change freely (phone hotspots
// hand out new addresses and block mDNS). Until a beacon arrives: PI_IP, else broadcast.
void startTarget() {
#ifdef PI_IP
  target.fromString(PI_IP);
  Serial.printf("%s sending to %s:%d (PI_IP, until a gateway beacon)\n", LOG_PREFIX, target.toString().c_str(), UDP_PORT);
#else
  target = WiFi.broadcastIP();
  Serial.printf("%s sending to %s:%d (broadcast, until a gateway beacon)\n", LOG_PREFIX, target.toString().c_str(), UDP_PORT);
#endif
  beacon.begin(BEACON_PORT);
}

void checkBeacon() {
  if (!beacon.parsePacket()) return;
  char buf[64];
  int n = beacon.read(buf, sizeof buf - 1);
  buf[n > 0 ? n : 0] = 0;
  IPAddress from = beacon.remoteIP();
  if (strstr(buf, "\"rtls\"") && strstr(buf, "\"gateway\"") && from != target) {   // any JSON spacing
    target = from;
    Serial.printf("%s sending to %s:%d (gateway beacon)\n", LOG_PREFIX, target.toString().c_str(), UDP_PORT);
  }
}

uint32_t rangeCount[3] = {0, 0, 0};   // per-anchor ranges since last rate report
uint32_t lastReport = 0;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);   // power save adds latency to every packet
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[T1] connecting to %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n%s ip %s\n", LOG_PREFIX, WiFi.localIP().toString().c_str());
  startTarget();
}

void newRange() {
  DW1000Device *dev = DW1000Ranging.getDistantDevice();
  uint16_t addr = dev->getShortAddress();   // 0xA1 -> "A1"
  float range = dev->getRange();
  if (addr < 0xA1 || addr > 0xA3 || range <= 0.0f || range > MAX_RANGE_M) return;

  char pkt[128];
  snprintf(pkt, sizeof pkt,
           "{\"tag\":\"" TAG_ID "\",\"anchor\":\"A%d\",\"range\":%.3f,\"rxPower\":%.1f,\"fpPower\":%.1f}",
           addr - 0xA0, range, dev->getRXPower(), dev->getFPPower());
  Serial.println(pkt);
  rangeCount[addr - 0xA1]++;

  if (WiFi.status() == WL_CONNECTED) {
    udp.beginPacket(target, UDP_PORT);
    udp.write((const uint8_t *)pkt, strlen(pkt));
    udp.endPacket();
  }
}

void newDevice(DW1000Device *dev) {
  Serial.printf("[T1] anchor found: %X\n", dev->getShortAddress());
}

void inactiveDevice(DW1000Device *dev) {
  Serial.printf("[T1] anchor lost: %X\n", dev->getShortAddress());
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  connectWiFi();
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI);
  DW1000Ranging.initCommunication(PIN_RST, DW_CS, PIN_IRQ);
  char id[128];
  DW1000.getPrintableDeviceIdentifier(id);   // "DECA - model: 1, version: 3, revision: 0" = wiring OK
  Serial.printf("[T1] DW1000 id: %s\n", id);
  DW1000Ranging.attachNewRange(newRange);
  DW1000Ranging.attachNewDevice(newDevice);
  DW1000Ranging.attachInactiveDevice(inactiveDevice);
  DW1000Ranging.startAsTag(tag_addr, DW1000.MODE_LONGDATA_RANGE_LOWPOWER, false);
  Serial.println("[T1] tag ready");
}

void loop() {
  DW1000Ranging.loop();
  checkBeacon();

  // Every 5 s print ranges/s per anchor: use the lowest as ranging.updateRateHz.
  uint32_t now = millis();
  if (now - lastReport >= 5000) {
    float s = (now - lastReport) / 1000.0f;
    Serial.printf("[T1] rate Hz  A1 %.1f  A2 %.1f  A3 %.1f\n",
                  rangeCount[0] / s, rangeCount[1] / s, rangeCount[2] / s);
    rangeCount[0] = rangeCount[1] = rangeCount[2] = 0;
    lastReport = now;
    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();   // hotspot dropped: keep ranging, retry
  }
}
