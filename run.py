"""
INCOSE Requirements Assistant
Run this once to set up, then again to start the app.

    python run.py

That's it.
"""

import subprocess
import sys
import os
import shutil
import time
import socket
import webbrowser
import re
from pathlib import Path

ROOT     = Path(__file__).parent
BACKEND  = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'
ENV_FILE    = BACKEND / '.env'
ENV_EXAMPLE = BACKEND / '.env.example'


# ── Port utilities ────────────────────────────────────────────────────────────

def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('localhost', port)) == 0

def _free_port(port):
    """Kill whatever process is holding the given port."""
    if not _port_in_use(port):
        return
    print(f"  Port {port} already in use — stopping existing process...")
    try:
        if sys.platform == 'win32':
            result = subprocess.run(
                ['powershell', '-Command',
                 f'(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess'],
                capture_output=True, text=True
            )
            pid = result.stdout.strip()
            if pid and pid.isdigit():
                subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
        else:
            pid = subprocess.check_output(['lsof', '-ti', f':{port}']).decode().strip()
            if pid:
                subprocess.run(['kill', '-9', pid], capture_output=True)
        time.sleep(1)
    except Exception:
        pass


# ── Step 1: Auto-install Python packages if missing ──────────────────────────

def _pip_packages_ok():
    try:
        import fastapi, anthropic, uvicorn
        return True
    except ImportError:
        return False

def _ensure_pip():
    if _pip_packages_ok():
        return
    print("[Setup] Installing Python packages (first time, ~1 min)...")
    r = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r',
         str(BACKEND / 'requirements.txt')],
    )
    if r.returncode != 0:
        print("\nERROR: pip install failed. Check the output above.")
        sys.exit(1)
    print("[Setup] Python packages installed.\n")


# ── Step 2: Auto-install Node packages if missing ────────────────────────────

def _npm():
    n = shutil.which('npm')
    if not n:
        print("ERROR: Node.js not found on this computer.")
        print("Install it from https://nodejs.org/ (click the LTS button), then run this again.")
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
    print("[Setup] Node packages installed.\n")


# ── Step 3: Create .env if missing, prompt user to fill in key ───────────────

def _ensure_env():
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
        else:
            ENV_FILE.write_text(
                "AI_PROVIDER=anthropic\n"
                "ANTHROPIC_API_KEY=\n"
                "OPENAI_API_KEY=\n"
                "OLLAMA_URL=http://localhost:11434\n"
                "OLLAMA_MODEL=llama3\n"
            )

    content = ENV_FILE.read_text()

    m = re.search(r'^AI_PROVIDER\s*=\s*(\S+)', content, re.MULTILINE)
    provider = m.group(1).strip().lower() if m else 'anthropic'

    if provider == 'anthropic':
        m = re.search(r'^ANTHROPIC_API_KEY\s*=\s*(.+)', content, re.MULTILINE)
        key = m.group(1).strip() if m else ''
    elif provider == 'openai':
        m = re.search(r'^OPENAI_API_KEY\s*=\s*(.+)', content, re.MULTILINE)
        key = m.group(1).strip() if m else ''
    else:
        key = 'ollama-no-key-needed'

    placeholder_values = ('', 'sk-ant-YOUR-KEY-HERE', 'sk-YOUR-KEY-HERE', 'YOUR-KEY-HERE')

    if key in placeholder_values:
        print()
        print("=" * 54)
        print("  ACTION REQUIRED — Add your API key")
        print("=" * 54)
        print()
        print("  The file  backend/.env  has been created.")
        print("  Open it in VSCode and fill in your API key:")
        print()
        print("    For Anthropic (Claude):")
        print("      AI_PROVIDER=anthropic")
        print("      ANTHROPIC_API_KEY=sk-ant-...")
        print()
        print("    For OpenAI (GPT-4o):")
        print("      AI_PROVIDER=openai")
        print("      OPENAI_API_KEY=sk-...")
        print()
        print("  Save the file, then run  python run.py  again.")
        print()
        print("=" * 54)
        print()
        sys.exit(0)


# ── Step 4: Clear ports and start both servers ────────────────────────────────

def _start():
    npm = _npm()

    print()
    print("=" * 54)
    print("  INCOSE Requirements Assistant")
    print("=" * 54)
    print()

    _free_port(8000)
    _free_port(3001)

    print("Starting backend  (port 8000)...")
    backend_proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'main:app',
         '--host', '0.0.0.0', '--port', '8000'],
        cwd=str(BACKEND),
    )

    time.sleep(3)

    print("Starting frontend (port 3001)...")
    frontend_proc = subprocess.Popen(
        [npm, 'run', 'dev'],
        cwd=str(FRONTEND),
    )

    time.sleep(4)
    webbrowser.open('http://localhost:3001')

    print()
    print("  App is running at  http://localhost:3001")
    print("  Press Ctrl+C to stop.")
    print()

    try:
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        backend_proc.terminate()
        frontend_proc.terminate()
        backend_proc.wait()
        frontend_proc.wait()
        print("Stopped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    _ensure_pip()
    _ensure_npm()
    _ensure_env()
    _start()
