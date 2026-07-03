"""
kill_port.py — Kill any process listening on a given port (Windows).

Usage:
    .venv/Scripts/python scripts/kill_port.py           # default: port 8501
    .venv/Scripts/python scripts/kill_port.py 8501
    .venv/Scripts/python scripts/kill_port.py --list     # list all listening ports
"""

import subprocess
import sys
import argparse


def list_listening_ports():
    """List all listening TCP ports."""
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True
    )
    lines = []
    for line in result.stdout.split("\n"):
        if "LISTENING" in line:
            parts = line.strip().split()
            local = parts[1]
            pid = parts[-1]
            lines.append(f"  {local:<25} PID {pid}")
    return lines


def get_pid_on_port(port: int) -> list[str]:
    """Return list of PIDs listening on the given port."""
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True
    )
    pids = []
    for line in result.stdout.split("\n"):
        if f":{port}" in line and "LISTENING" in line:
            parts = line.strip().split()
            pid = parts[-1]
            if pid not in pids:
                pids.append(pid)
    return pids


def kill_pid(pid: str) -> bool:
    """Kill a process by PID. Returns True if successful."""
    result = subprocess.run(
        ["taskkill", "/F", "/PID", pid], capture_output=True, text=True
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Kill process on a port")
    parser.add_argument("port", nargs="?", type=int, default=8501,
                        help="Port number (default: 8501)")
    parser.add_argument("--list", action="store_true",
                        help="List all listening ports")
    args = parser.parse_args()

    if args.list:
        print("Listening ports:")
        for l in list_listening_ports():
            print(l)
        return

    port = args.port
    pids = get_pid_on_port(port)

    if not pids:
        print(f"No process listening on port {port}")
        return

    for pid in pids:
        print(f"Killing PID {pid} on port {port}...")
        if kill_pid(pid):
            print(f"  ✓ Killed PID {pid}")
        else:
            print(f"  ✗ Failed to kill PID {pid}")


if __name__ == "__main__":
    main()
