// Copy to secrets.h (git-ignored) and fill in. The server (Pi or laptop) must join the same hotspot.
#define WIFI_SSID "your-hotspot-name"
#define WIFI_PASS "your-hotspot-password"

// Optional starting address (`hostname -I` on the server). Either way the node switches to
// whichever gateway beacons on port 9001, so a changed hotspot IP needs no reflash. With
// neither it broadcasts until the first beacon (a phone hotspot drops ~1 in 3 broadcasts).
// #define PI_IP "10.76.162.90"
