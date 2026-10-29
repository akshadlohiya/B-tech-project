#!/usr/bin/env bash
# Install the RTLS gateway and viewer as boot services on the Raspberry Pi.
# The backend (rtls-server) is set up separately, see PI_SETUP.md.
#
#   sudo deploy/install-services.sh <map-key>      e.g. sudo deploy/install-services.sh 4f41ed2f96
#
# Re-run it to change the map. Logs: journalctl -u rtls-gateway -f   /   journalctl -u rtls-viewer -f
set -euo pipefail

MAP=${1:?usage: sudo $0 <map-key>}
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
USER_NAME=${SUDO_USER:?run with sudo from your normal user, not as root}
REPO=$(cd "$(dirname "$0")/.." && pwd)

# A gateway or viewer started by hand holds UDP 9000 / TCP 5173: stop it so the services can start.
pkill -f "anchor-source/main.py" && echo "stopped a gateway started by hand" || true
pkill -f "vite --host" && echo "stopped a viewer started by hand" || true
sleep 1

for svc in rtls-gateway rtls-viewer; do
  sed -e "s|@USER@|$USER_NAME|g" -e "s|@REPO@|$REPO|g" -e "s|@MAP@|$MAP|g" \
      "$REPO/deploy/$svc.service" > "/etc/systemd/system/$svc.service"
done
systemctl daemon-reload
systemctl enable rtls-server rtls-gateway rtls-viewer >/dev/null
systemctl restart rtls-gateway rtls-viewer
sleep 3

for svc in rtls-server rtls-gateway rtls-viewer; do
  printf "%-13s %s\n" "$svc" "$(systemctl is-active "$svc")"
done
echo "viewer: http://$(hostname -I | awk '{print $1}'):5173/?map=$MAP"
