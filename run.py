from __future__ import annotations

import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:5173"


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _is_port_open(host, port):
            return True
        time.sleep(0.2)
    return False


def _wait_for_http(url: str, timeout_seconds: float) -> bool:
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except URLError:
            pass
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _warm_backend(url: str) -> None:
    try:
        with urlopen(url, timeout=20) as response:
            if 200 <= response.status < 300:
                print("Backend warm-up complete.")
            else:
                print(f"Backend warm-up responded with status {response.status}.")
    except Exception as exc:
        print(f"Backend warm-up failed: {exc}")


def _warm_backend_async() -> None:
    def _task() -> None:
        if _wait_for_http(f"{BACKEND_URL}/api/health", timeout_seconds=25):
            _warm_backend(f"{BACKEND_URL}/api/aqi/grid")
        else:
            print("Backend did not become ready in time for warm-up.")

    threading.Thread(target=_task, daemon=True).start()


def _start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    print(f"Starting {name} in {cwd}...")
    return subprocess.Popen(command, cwd=str(cwd))


def _stop_process(name: str, process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return

    print(f"Stopping {name} (pid {process.pid})...")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    backend_process: subprocess.Popen | None = None
    frontend_process: subprocess.Popen | None = None

    stop_requested = False

    def _request_stop(signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        print(f"Received signal {signum}. Shutting down...")

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    try:
        backend_process = _start_process(
            "backend",
            [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"],
            BACKEND_DIR,
        )
        frontend_process = _start_process(
            "frontend",
            [sys.executable, "-m", "http.server", "5173"],
            FRONTEND_DIR,
        )

        if _wait_for_port("127.0.0.1", 5173, timeout_seconds=12):
            webbrowser.open(FRONTEND_URL)
            print(f"Opened {FRONTEND_URL} in your default browser.")
        else:
            print(f"Frontend did not open port 5173 in time. Open {FRONTEND_URL} manually.")

        # Warm backend in background so first map load is better, without delaying browser open.
        _warm_backend_async()

        print(f"Backend:  {BACKEND_URL}")
        print(f"Frontend: {FRONTEND_URL}")
        print("Press Ctrl+C to stop both servers.")

        while not stop_requested:
            backend_exit = backend_process.poll() if backend_process else 0
            frontend_exit = frontend_process.poll() if frontend_process else 0

            if backend_exit is not None:
                print(f"Backend exited with code {backend_exit}.")
                break
            if frontend_exit is not None:
                print(f"Frontend exited with code {frontend_exit}.")
                break
            time.sleep(0.4)

    finally:
        _stop_process("frontend", frontend_process)
        _stop_process("backend", backend_process)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
