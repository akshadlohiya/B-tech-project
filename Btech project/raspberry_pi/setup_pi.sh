#!/bin/bash
# ==============================================================================
# Setup Script for Raspberry Pi 4 Model B (Raspberry Pi OS / Debian Bookworm)
# 3D RTLS Warehouse Localization Tracker
# ==============================================================================

set -e

echo "========================================================"
echo "🍓 Initializing Raspberry Pi 4 RTLS Tracking Setup..."
echo "========================================================"

# Update system package lists
echo "[1/4] Updating package index..."
sudo apt-get update -y

# Install Python venv and wireless tools if missing
echo "[2/4] Installing system prerequisites (python3-venv, wireless-tools, iw)..."
sudo apt-get install -y python3-venv python3-pip wireless-tools iw net-tools

# Create Python Virtual Environment (PEP 668 compliant)
echo "[3/4] Creating Python virtual environment (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created successfully."
else
    echo "Existing virtual environment found."
fi

# Activate venv and install required packages
echo "[4/4] Installing Python dependencies inside virtual environment..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Make python script executable
chmod +x pi_wifi_tracker.py

echo ""
echo "========================================================"
echo "✅ Raspberry Pi RTLS Setup Complete!"
echo "========================================================"
echo ""
echo "To calibrate Wi-Fi signal at 1 meter:"
echo "   source venv/bin/activate"
echo "   python3 pi_wifi_tracker.py --calibrate"
echo ""
echo "To start live dynamic distance tracking:"
echo "   source venv/bin/activate"
echo "   python3 pi_wifi_tracker.py --server http://<YOUR_PC_IP>:3000"
echo ""
echo "========================================================"
