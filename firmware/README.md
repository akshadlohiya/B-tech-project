# ESP32 + DW1000 firmware

Four nodes, each an ESP32 DevKit wired to one DW1000:

| Board | Sketch | Setting | Short address | Wi-Fi |
|---|---|---|---|---|
| Anchor A1 | `uwb_anchor` | `ANCHOR_NUM 1` | `A1` | no |
| Anchor A2 | `uwb_anchor` | `ANCHOR_NUM 2` | `A2` | no |
| Anchor A3 | `uwb_anchor` | `ANCHOR_NUM 3` | `A3` | no |
| Tag T1 | `uwb_tag` | `secrets.h` | `7D` | yes, phone hotspot |

The tag ranges to each anchor (DS-TWR) and sends one UDP/JSON datagram per range to
port 9000 on the hotspot's broadcast address. The Pi gateway (`SOURCE=hardware`) picks
these up wherever its IP lands. The anchors only need USB power.

## Wiring (identical on all four)

| DW1000 | ESP32 |
|---|---|
| VDD | **3V3** (never 5V) |
| GND | GND |
| SPICLK | GPIO18 |
| SPIMISO | GPIO19 |
| SPIMOSI | GPIO23 |
| SPICSn | GPIO4 |
| IRQ | GPIO34 |
| RSTn | GPIO27 |

Keep the jumpers under 10 cm, and put a 10 µF cap across VDD and GND near the module if you have one.

## Toolchain

1. Arduino IDE → Boards Manager → install **esp32 by Espressif**. Board: **ESP32 Dev Module**.
2. Download <https://github.com/jremington/UWB-Indoor-Localization_Arduino>. Zip the
   `DW1000_library` folder and add it with Sketch → Include Library → Add .ZIP Library.

## Bring-up order

1. **Wiring check (each board).** Flash `uwb_anchor` and open Serial Monitor at 115200. The boot line
   `DW1000 id: DECA - model: 1, version: 3, revision: 0` means SPI works. All zeros or `FFFF`
   points to the SPI wires, 3V3 or GND.
2. **Pair test.** Flash one board as A1 and one as T1, and watch T1's serial at 1, 2 and 3 m.
   Before the hotspot is set up, the tag waits on Wi-Fi, so create `secrets.h` first.
3. **Antenna delay (each anchor).** Flash the library's `ESP32_anchor_autocalibrate` on the
   anchor with the tag at a measured distance. Put the printed delay into that anchor's
   `ANTENNA_DELAY` and reflash. Check that the ranges land within ±10 cm of the tape.
4. **All nodes.** Flash A2 and A3, then T1:
   ```
   cp uwb_tag/secrets.example.h uwb_tag/secrets.h   # git-ignored; fill in SSID/password
   ```
   T1's serial prints every packet it sends, plus `rate Hz  A1 … A2 … A3 …` every 5 s. Use the
   lowest of those rates as `ranging.updateRateHz` in the map.

Then follow `PI_SETUP.md` (step 6 onwards) to bring the Pi onto the hotspot and run the gateway.

## Troubleshooting

| Symptom | Check |
|---|---|
| `DW1000 id` all zeros | SPI wiring, 3V3, common GND |
| Tag never prints `anchor found` | Anchor powered? Same `MODE_LONGDATA_RANGE_LOWPOWER` on both? IRQ wire on GPIO34 |
| Ranges off by a constant | Antenna delay (step 3) |
| Serial OK but Pi gets nothing | Pi on the same hotspot? `sudo tcpdump -n udp port 9000`. Some phones block broadcast: set `PI_IP` in `secrets.h` |
