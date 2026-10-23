import os
import sys
import time
import socket
import argparse
import urllib.request
import json

# Auto-install paramiko / scp if missing on Windows
try:
    import paramiko
    from scp import SCPClient
except ImportError:
    print("Paramiko / SCP not found. Installing paramiko and scp...")
    os.system(f"{sys.executable} -m pip install paramiko scp")
    import paramiko
    from scp import SCPClient

# Default Raspberry Pi configuration
DEFAULT_HOSTS = ["10.1.238.88", "10.158.134.90", "192.168.1.40", "akshad.local", "akshad"]
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
        spin_char = spinner[attempt % len(spinner)]
        for host in hosts:
            try:
                ip = socket.gethostbyname(host)
            except socket.gaierror:
                ip = host

            if test_tcp_port(ip, SSH_PORT, timeout=1.0):
                print(f"\n\n✅ SUCCESS: Raspberry Pi detected online at {host} ({ip})!")
                return ip

        sys.stdout.write(f"\r[{spin_char}] Attempt {attempt}: Waiting for Raspberry Pi to power on / join Wi-Fi...")
        sys.stdout.flush()
        attempt += 1
        time.sleep(2)


def connect_and_sync_backend(pi_ip):
    """Connect over SSH, upload backend files, and restart the RTLS service."""
    print(f"\n🔑 Connecting to Raspberry Pi ({pi_ip}) via SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=pi_ip,
            port=SSH_PORT,
            username=SSH_USER,
            password=SSH_PASS,
            timeout=10,
            banner_timeout=15,
            auth_timeout=10,
        )
        print("✅ SSH Connection Established!")
    except Exception as e:
        print(f"❌ Failed to connect via SSH: {e}")
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
    url = f"http://{pi_ip}:{SERVER_PORT}/health"
    print(f"\n📡 Verifying Server Health Endpoint: {url}")
    try:
        req = urllib.request.urlopen(url, timeout=5)
        if req.getcode() == 200:
            data = json.loads(req.read().decode())
            print("✅ Health Check Passed!")
            print(f"   Device:  {data.get('device')}")
            print(f"   Records: {data.get('total_database_records')}")
            return True
    except Exception as e:
        print(f"⚠️ Health check ping: {e}")
        return False


def monitor_database_live(pi_ip):
    """Continuously poll and stream newly inserted database entries to console."""
    print("\n" + "=" * 65)
    print(f"📊 LIVE SQLITE DATABASE MONITOR: http://{pi_ip}:{SERVER_PORT}/api/database")
    print("   Showing incoming tag coordinates (Press Ctrl+C to exit monitor)...")
    print("=" * 65)

    seen_ids = set()
    try:
        while True:
            try:
                url = f"http://{pi_ip}:{SERVER_PORT}/api/database?limit=10"
                req = urllib.request.urlopen(url, timeout=3)
                rows = json.loads(req.read().decode())
                # Rows come ordered DESC (newest first)
                for r in reversed(rows):
                    rec_id = r.get("id")
                    if rec_id and rec_id not in seen_ids:
                        seen_ids.add(rec_id)
                        print(f"💾 [DB Entry #{rec_id:04d}] Tag: {r.get('tag'):<10} | Name: {r.get('name'):<12} | "
                              f"X: {r.get('x'):>6.2f}m  Y: {r.get('y'):>5.2f}m  Z: {r.get('z'):>6.2f}m | Time: {r.get('time')}")
            except Exception:
                pass
            time.sleep(1.2)
    except KeyboardInterrupt:
        print("\n\n👋 Monitor closed. Raspberry Pi server and database remain active!")


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 4 Auto-Connect & Database Initializer")
    parser.add_argument("--host", default=None, help="Raspberry Pi IP address or hostname")
    parser.add_argument("--no-monitor", action="store_true", help="Skip the live database stream")
    args = parser.parse_args()

    hosts = [args.host] if args.host else DEFAULT_HOSTS

    # Step 1: Wait for Raspberry Pi to come online
    pi_ip = wait_for_raspberry_pi(hosts)

    # Step 2: SSH sync and service startup
    ok = connect_and_sync_backend(pi_ip)
    if not ok:
        print("❌ Initialization failed. Please verify Raspberry Pi credentials and network.")
        return

    # Step 3: Verify API
    time.sleep(1)
    verify_database_api(pi_ip)

    print("\n" + "=" * 65)
    print("🎉 RASPBERRY PI 4 & DATABASE FULLY INITIALIZED!")
    print(f"   Backend:   http://{pi_ip}:{SERVER_PORT}")
    print(f"   Database:  http://{pi_ip}:{SERVER_PORT}/api/database")
    print(f"   Analytics: http://{pi_ip}:{SERVER_PORT}/api/analytics")
    print(f"   Tags:      http://{pi_ip}:{SERVER_PORT}/api/tags")
    print("=" * 65)

    # Step 4: Stream live database records
    if not args.no_monitor:
        monitor_database_live(pi_ip)


if __name__ == "__main__":
    main()
