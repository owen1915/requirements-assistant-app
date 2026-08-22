"""
ICAIv2 Studio — upload SME feedback, run the pipeline, read the induced rules.

    python run_icai_studio.py

Ports 8010 (API) and 3002 (UI), so this runs alongside the prototype on 8000/3001.

Keys are read from the same places the rest of the repo reads them:
ui_prototype/backend/.env, then a repo-root .env if present. A DRY RUN needs no
keys at all; a live run needs ANTHROPIC_API_KEY (generation and testing) and
OPENAI_API_KEY (the clustering embeddings — Anthropic has no embeddings endpoint).
"""

import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
FRONTEND = ROOT / 'icai_v2' / 'app' / 'frontend'

API_PORT = 8010
UI_PORT = 3002


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('localhost', port)) == 0


def _free_port(port):
    if not _port_in_use(port):
        return
    print(f"  Port {port} already in use - stopping existing process...")
    try:
        if sys.platform == 'win32':
            result = subprocess.run(
                ['powershell', '-Command',
                 f'(Get-NetTCPConnection -LocalPort {port} -State Listen '
                 f'-ErrorAction SilentlyContinue).OwningProcess'],
                capture_output=True, text=True)
            pids = [p for p in result.stdout.split() if p.isdigit()]
        else:
            pids = subprocess.check_output(
                ['lsof', '-ti', f':{port}']).decode().split()
        for pid in pids:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
            else:
                subprocess.run(['kill', '-9', pid], capture_output=True)
        time.sleep(1)
    except Exception:
        pass

    if _port_in_use(port):
        print(f"  ERROR: port {port} is still held by another process. "
              f"Close it and try again.")
        sys.exit(1)


def _ensure_python():
    try:
        import fastapi, uvicorn, sklearn  # noqa: F401
        return
    except ImportError:
        pass
    print("[Setup] Installing Python packages (first time, ~1 min)...")
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-e',
                        f'{ROOT}[app,research]'])
    if r.returncode != 0:
        print("\nERROR: pip install failed. Check the output above.")
        sys.exit(1)


def _npm():
    n = shutil.which('npm')
    if not n:
        print("ERROR: Node.js not found. Install it from https://nodejs.org/ "
              "(the LTS button), then run this again.")
        sys.exit(1)
    return n


def _ensure_npm():
    if (FRONTEND / 'node_modules').exists():
        return
    npm = _npm()
    print("[Setup] Installing Node packages (first time, ~1 min)...")
    r = subprocess.run([npm, 'install'], cwd=str(FRONTEND))
    if r.returncode != 0:
        print("\nERROR: npm install failed. Check the output above.")
        sys.exit(1)


def main():
    _ensure_python()
    _ensure_npm()
    npm = _npm()

    print()
    print("=" * 54)
    print("  ICAIv2 Studio")
    print("=" * 54)
    print()

    _free_port(API_PORT)
    _free_port(UI_PORT)

    print(f"Starting API      (port {API_PORT})...")
    api = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'icai_v2.app.backend.server:app',
         '--host', '0.0.0.0', '--port', str(API_PORT)],
        cwd=str(ROOT))

    time.sleep(3)

    print(f"Starting frontend (port {UI_PORT})...")
    ui = subprocess.Popen([npm, 'run', 'dev'], cwd=str(FRONTEND))

    time.sleep(4)
    webbrowser.open(f'http://localhost:{UI_PORT}')

    print()
    print(f"  Studio is running at  http://localhost:{UI_PORT}")
    print("  Press Ctrl+C to stop.")
    print()

    try:
        api.wait()
        ui.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        api.terminate()
        ui.terminate()
        api.wait()
        ui.wait()
        print("Stopped.")


if __name__ == '__main__':
    main()
