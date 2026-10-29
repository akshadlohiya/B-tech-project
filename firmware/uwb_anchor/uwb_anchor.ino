// UWB anchor node: ESP32 + DW1000, fixed position, USB power only.
//
// Answers the tag's DS-TWR polls. It needs no Wi-Fi: the tag reports every
// range to the Pi. Flash once per anchor with ANCHOR_NUM = 1, 2, 3 and that
// board's calibrated ANTENNA_DELAY (see firmware/README.md).
//
// Library: jremington/UWB-Indoor-Localization_Arduino (DW1000_library).

#include <SPI.h>
#include "DW1000Ranging.h"
#include "DW1000.h"

// ---- per-board settings ---------------------------------------------------
#define ANCHOR_NUM    1        // 1 -> A1, 2 -> A2, 3 -> A3
#define ANTENNA_DELAY 16384    // replace with this board's autocalibrated value

// ---- wiring (same on every node) -------------------------------------------
#define SPI_SCK  18
#define SPI_MISO 19
#define SPI_MOSI 23
#define DW_CS    4
#define PIN_RST  27
#define PIN_IRQ  34

// The first byte is the short address the tag sees (0xA1 -> "A1").
#if ANCHOR_NUM == 1
char anchor_addr[] = "A1:00:5B:D5:A9:9A:E2:9C";
#elif ANCHOR_NUM == 2
char anchor_addr[] = "A2:00:5B:D5:A9:9A:E2:9C";
#elif ANCHOR_NUM == 3
char anchor_addr[] = "A3:00:5B:D5:A9:9A:E2:9C";
#else
#error "ANCHOR_NUM must be 1, 2 or 3"
#endif

void newRange() {
  DW1000Device *dev = DW1000Ranging.getDistantDevice();
  Serial.printf("[A%d] tag %X  range %.2f m  rx %.1f dBm  fp %.1f dBm\n", ANCHOR_NUM,
                dev->getShortAddress(), dev->getRange(), dev->getRXPower(), dev->getFPPower());
}

void newDevice(DW1000Device *dev) {
  Serial.printf("[A%d] tag joined: %X\n", ANCHOR_NUM, dev->getShortAddress());
}

void inactiveDevice(DW1000Device *dev) {
  Serial.printf("[A%d] tag lost: %X\n", ANCHOR_NUM, dev->getShortAddress());
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI);
  DW1000Ranging.initCommunication(PIN_RST, DW_CS, PIN_IRQ);
  char id[128];
  DW1000.getPrintableDeviceIdentifier(id);   // "DECA - model: 1, version: 3, revision: 0" = wiring OK
  Serial.printf("[A%d] DW1000 id: %s\n", ANCHOR_NUM, id);
  DW1000.setAntennaDelay(ANTENNA_DELAY);
  DW1000Ranging.attachNewRange(newRange);
  DW1000Ranging.attachBlinkDevice(newDevice);
  DW1000Ranging.attachInactiveDevice(inactiveDevice);
  // false = keep the fixed short address above instead of a random one
  DW1000Ranging.startAsAnchor(anchor_addr, DW1000.MODE_LONGDATA_RANGE_LOWPOWER, false);
  Serial.printf("[A%d] anchor ready, antenna delay %d\n", ANCHOR_NUM, ANTENNA_DELAY);
}

void loop() {
  DW1000Ranging.loop();
}
