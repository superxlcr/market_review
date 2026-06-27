"""
restart_streamlit.py — Kill, clear pycache, restart Streamlit on port 8501.

Usage: .venv/Scripts/python restart_streamlit.py
"""

import subprocess
import os
import shutil
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8501


def kill_on_port(port: int):
    """Kill any process listening on the given port (Windows)."""
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True
    )
    killed = 0
    for line in result.stdout.split("\n"):
        if f":{port}" in line and "LISTENING" in line:
            parts = line.strip().split()
            pid = parts[-1]
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            print(f"  Killed PID {pid} on port {port}")
            killed += 1
    if killed == 0:
        print(f"  (no process on port {port})")
    return killed


def clear_pycache():
    """Remove all __pycache__ dirs under project root, skip .venv."""
    removed = 0
    for root, dirs, _files in os.walk(PROJECT_ROOT):
        # Skip .venv entirely — third-party cache is irrelevant
        if ".venv" in root.split(os.sep):
            continue
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                shutil.rmtree(path)
                removed += 1
    print(f"  Removed {removed} __pycache__ dirs")
    return removed


def start_streamlit():
    """Start Streamlit in background, wait for it to come up."""
    log_path = os.path.join(PROJECT_ROOT, "logs", "streamlit_restart.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run",
                "dashboard/app.py", "--server.port", str(PORT),
            ],
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    print(f"  Starting Streamlit on port {PORT}...")
    time.sleep(5)

    # Check for startup errors
    with open(log_path, "r") as f:
        lines = f.readlines()
    errors = [l for l in lines if "error" in l.lower() or "traceback" in l.lower()]
    if errors:
        print("  [WARN] Startup errors:")
        for e in errors:
            print(f"    {e.strip()}")
    else:
        print("  [OK] No startup errors")

    # Show the "started" line
    for l in lines:
        if "started" in l.lower():
            print(f"  {l.strip()}")
            break


def main():
    print("=== Restart Streamlit ===")
    print("[1/3] Kill processes on port 8501...")
    kill_on_port(PORT)

    print("[2/3] Clear pycache...")
    clear_pycache()

    print("[3/3] Start Streamlit...")
    start_streamlit()

    print("Done.")


if __name__ == "__main__":
    main()
