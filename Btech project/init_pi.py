#!/usr/bin/env python3
"""
================================================================================
🍓 Raspberry Pi 4 RTLS Auto-Connect & Remote Initializer
================================================================================
This script runs on your PC/Laptop. It:
1. Waits and continuously polls until the Raspberry Pi connects to the network.
2. Connects to the Pi over SSH and synchronizes backend code.
3. Initializes the SQLite database (tag, name, x, y, z, time).
4. Verifies the RTLS Edge Server service is running.
5. Provides a live streaming monitor of incoming tag coordinates.
================================================================================
"""

import socket
import time
import sys
import os
import json
import io
import urllib.request
from urllib.error import URLError

# Enable UTF-8 for Windows console
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    import paramiko
    from scp import SCPClient
except ImportError:
    print("Paramiko / SCP not found. Installing paramiko and scp...")
    os.system(f"{sys.executable} -m pip install paramiko scp")
    import paramiko
    from scp import SCPClient

# Default Raspberry Pi configuration
DEFAULT_HOSTS = ["192.168.1.40", "akshad.local", "akshad"]
SSH_USER = "akshad"
SSH_PASS = "Maths@15"
SSH_PORT = 22
SERVER_PORT = 3000

WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL_BACKEND_DIR = os.path.join(WORKSPACE_ROOT, "backend")
REMOTE_BACKEND_DIR = f"/home/{SSH_USER}/B-tech-project/backend"
REMOTE_PI_DIR = f"/home/{SSH_USER}/B-tech-project/raspberry_pi"


def test_tcp_port(host, port, timeout=1.5):
    """Test if a TCP port is open and responding on the remote host."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def wait_for_raspberry_pi(hosts=DEFAULT_HOSTS):
    """Poll until the Raspberry Pi is discovered online on the network."""
    print("==================================================================")
    print("🔍 Searching for Raspberry Pi 4 on local network...")
    print(f"   Target hosts: {', '.join(hosts)}")
    print("==================================================================")

    attempt = 1
    spinner = ["|", "/", "-", "\\"]
    
    while True:
        for host in hosts:
            try:
                # Try resolving hostname to IP if it's mDNS (e.g. akshad.local)
                ip = socket.gethostbyname(host)
            except Exception:
                ip = host

            # Check SSH port 22
            if test_tcp_port(ip, SSH_PORT, timeout=1.0):
                print(f"\n\n🎉 SUCCESS: Raspberry Pi detected online at {host} ({ip})!")
                return ip

        # Show waiting spinner
        spin_char = spinner[attempt % len(spinner)]
        sys.stdout.write(f"\r[{spin_char}] Attempt {attempt}: Waiting for Raspberry Pi to power on / join Wi-Fi...")
        sys.stdout.flush()
        attempt += 1
        time.sleep(2)


def initialize_pi_and_database(pi_ip):
    """Connect over SSH, sync files, and start/verify the server and database."""
    print(f"\n🔐 Connecting to {SSH_USER}@{pi_ip} via SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(pi_ip, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=10)
        print("✅ SSH Authentication successful!")
    except Exception as e:
        print(f"❌ SSH Connection failed: {e}")
        return False

    # 1. Ensure remote directories exist
    print(f"\n📂 Verifying directories on Raspberry Pi...")
    ssh.exec_command(f"mkdir -p {REMOTE_BACKEND_DIR} {REMOTE_PI_DIR}")
    time.sleep(0.5)

    # 2. Upload/Sync backend files
    print(f"📤 Synchronizing backend code to Raspberry Pi...")
    files_to_sync = ["server.js", "database.js", "analytics.js", "package.json"]
    with SCPClient(ssh.get_transport()) as scp:
        for f in files_to_sync:
            loc = os.path.join(LOCAL_BACKEND_DIR, f)
            if os.path.exists(loc):
                scp.put(loc, remote_path=f"{REMOTE_BACKEND_DIR}/{f}")
                print(f"   Synced: {f}")

    # 3. Restart or start rtls-server.service
    print(f"\n🚀 Starting / Restarting RTLS Edge Server & SQLite database...")
    restart_cmd = f"echo {SSH_PASS} | sudo -S systemctl restart rtls-server.service"
    stdin, stdout, stderr = ssh.exec_command(restart_cmd)
    stdout.channel.recv_exit_status()
    time.sleep(2)

    # 4. Check service status
    status_cmd = f"echo {SSH_PASS} | sudo -S systemctl is-active rtls-server.service"
    stdin, stdout, stderr = ssh.exec_command(status_cmd)
    service_status = stdout.read().decode().strip()
    print(f"   Server Service Status: {service_status.upper()}")

    ssh.close()
    return True


def verify_database_api(pi_ip):
    """Verify HTTP API and database endpoints from this device."""
    base_url = f"http://{pi_ip}:{SERVER_PORT}"
    print(f"\n📡 Testing HTTP API connection to {base_url} ...")

    # Wait up to 10 seconds for Node.js to accept HTTP connections
    for _ in range(10):
        try:
            req = urllib.request.urlopen(f"{base_url}/health", timeout=3)
            data = json.loads(req.read().decode())
            print(f"✅ Server Health: OK (Uptime: {data.get('uptime', 0):.1f}s)")
            break
        except Exception:
            time.sleep(1)
    else:
        print("⚠️ Warning: Server is starting, but HTTP /health did not respond immediately.")

    try:
        req = urllib.request.urlopen(f"{base_url}/api/database", timeout=3)
        records = json.loads(req.read().decode())
        print(f"✅ SQLite Database: Ready ({len(records)} existing records stored)")
        return True
    except Exception as e:
        print(f"⚠️ Could not query /api/database: {e}")
        return False


def live_tag_monitor(pi_ip):
    """Live monitor streaming new tag coordinate records as they are saved."""
    base_url = f"http://{pi_ip}:{SERVER_PORT}"
    print("\n==================================================================")
    print("📡 LIVE DATABASE STREAMING MONITOR")
    print(f"   Target Server: http://{pi_ip}:{SERVER_PORT}")
    print("   Press Ctrl+C at any time to exit monitor (Server keeps running on Pi)")
    print("==================================================================")

    last_seen_id = 0
    try:
        # Get starting record id
        req = urllib.request.urlopen(f"{base_url}/api/database?limit=1", timeout=3)
        initial = json.loads(req.read().decode())
        if initial:
            last_seen_id = initial[0].get("id", 0)
    except Exception:
        pass

    try:
        while True:
            try:
                req = urllib.request.urlopen(f"{base_url}/api/database?limit=10", timeout=3)
                rows = json.loads(req.read().decode())
                # Filter for new rows with id > last_seen_id
                new_rows = [r for r in rows if r.get("id", 0) > last_seen_id]
                new_rows.reverse()  # Print in chronological order

                for r in new_rows:
                    last_seen_id = max(last_seen_id, r.get("id", 0))
                    tag = r.get("tag", "Unknown")
                    name = r.get("name", "N/A")
                    x = r.get("x", 0.0)
                    y = r.get("y", 0.5)
                    z = r.get("z", 0.0)
                    t = r.get("time", "")
                    print(f"📍 [DB #{r.get('id')}] Tag: {tag:<12} | Name: {name:<18} | Pos: ({x:>5.2f}, {y:>4.2f}, {z:>5.2f}) | Time: {t}")

            except (URLError, Exception):
                pass

            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n\n👋 Monitor closed. Raspberry Pi server and database remain active!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Raspberry Pi 4 Auto-Connect & Database Initializer")
    parser.add_argument("--host", default=None, help="Raspberry Pi IP address or hostname")
    parser.add_argument("--no-monitor", action="store_true", help="Initialize and exit without starting live monitor")
    args = parser.parse_args()

    hosts = [args.host] if args.host else DEFAULT_HOSTS

    # Step 1: Wait for Raspberry Pi to come online
    pi_ip = wait_for_raspberry_pi(hosts)

    # Step 2: Initialize Pi and Database over SSH
    success = initialize_pi_and_database(pi_ip)
    if not success:
        print("❌ Initialization failed. Please verify Raspberry Pi credentials and network.")
        return

    # Step 3: Verify Database API
    verify_database_api(pi_ip)

    print("\n==================================================================")
    print("🎉 RASPBERRY PI 4 & DATABASE FULLY INITIALIZED!")
    print(f"   - Server URL:    http://{pi_ip}:{SERVER_PORT}")
    print(f"   - Database View: http://{pi_ip}:{SERVER_PORT}/api/database")
    print(f"   - Active Tags:   http://{pi_ip}:{SERVER_PORT}/api/tags")
    print("==================================================================")

    # Step 4: Launch live monitor if requested
    if not args.no_monitor:
        live_tag_monitor(pi_ip)


if __name__ == "__main__":
    main()
