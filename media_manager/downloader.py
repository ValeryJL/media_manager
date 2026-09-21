import subprocess
import time
import os
import sys
import json
import shutil
import urllib.request
from pathlib import Path

TRACKERS = ",".join([
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://9.rarbg.com:2810/announce",
    "udp://tracker.torrent.eu.org:451/announce"
])

_CONFIG_DIR  = os.path.expanduser("~/.config/media_manager")
_HOOK_SCRIPT = os.path.join(_CONFIG_DIR, "hook.bat" if os.name == "nt" else "hook.sh")
_STATE_FILE  = os.path.join(_CONFIG_DIR, ".hook_registered")
_RPC_URL     = "http://localhost:6800/jsonrpc"


def _refresh_windows_path():
    """Ensure os.environ['PATH'] contains latest paths from Windows Registry."""
    if os.name != "nt":
        return
    try:
        import winreg
        paths = []
        for root, subkey in [
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment")
        ]:
            try:
                with winreg.OpenKey(root, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    paths.append(val)
            except Exception:
                pass
        if paths:
            reg_paths = ";".join(paths)
            current_paths = os.environ.get("PATH", "")
            os.environ["PATH"] = reg_paths + ";" + current_paths
    except Exception:
        pass


def get_aria2c_binary() -> str:
    """Locate the aria2c binary, refreshing PATH on Windows if needed."""
    if os.name == "nt":
        _refresh_windows_path()
    found = shutil.which("aria2c")
    if found:
        return found
    # Check common WinGet / Chocolatey / Scoop locations on Windows
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            import glob
            matches = glob.glob(os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "aria2*"))
            for m in matches:
                for root, _, files in os.walk(m):
                    if "aria2c.exe" in files:
                        return os.path.join(root, "aria2c.exe")
    return "aria2c"


def _rpc(method: str, params=None) -> dict:
    """Send a JSON-RPC request to aria2c via urllib. Fast, reliable, and cross-platform."""
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": "mm"}).encode("utf-8")
    req = urllib.request.Request(
        _RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise ConnectionError(f"aria2c RPC connection failed: {e}")
    if "error" in data:
        err_msg = data["error"].get("message", str(data["error"]))
        raise RuntimeError(f"aria2c error: {err_msg}")
    return data


def create_hook_script() -> str:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    py_exe = sys.executable
    if os.name == "nt":
        hook_path = os.path.join(_CONFIG_DIR, "hook.bat")
        # In Windows, quote the arguments properly
        content = f'@echo off\r\n"{py_exe}" -m media_manager.cli hook "%~1" "%~2" "%~3"\r\n'
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(content)
        return hook_path
    else:
        hook_path = os.path.join(_CONFIG_DIR, "hook.sh")
        content = f'#!/usr/bin/env bash\n"{py_exe}" -m media_manager.cli hook "$1" "$2" "$3"\n'
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(hook_path, 0o755)
        return hook_path


def _daemon_running() -> bool:
    try:
        _rpc("aria2.getVersion")
        return True
    except Exception:
        return False


def _hook_known_registered() -> bool:
    return os.path.exists(_STATE_FILE)


def _kill_aria2c():
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "aria2c.exe"], capture_output=True)
    else:
        subprocess.run(["killall", "aria2c"], capture_output=True)
    time.sleep(1.0)


def _start_daemon():
    hook_path = create_hook_script()
    aria2_bin = get_aria2c_binary()
    args = [
        aria2_bin,
        "--enable-rpc",
        "--rpc-listen-all=false",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--seed-time=0",
        f"--bt-tracker={TRACKERS}",
        f"--on-download-complete={hook_path}",
        f"--on-bt-download-complete={hook_path}",
    ]
    
    popen_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    
    if os.name == "nt":
        # Windows does not support --daemon; use process flags for background detachment
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        popen_kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
    else:
        args.insert(3, "--daemon")

    subprocess.Popen(args, **popen_kwargs)
    # Wait up to 5 seconds for the daemon to respond
    for _ in range(10):
        time.sleep(0.5)
        if _daemon_running():
            break
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        f.write("ok\n")


def ensure_daemon():
    """
    Ensure aria2c is running with the hook registered.
    Only restarts if the state file is missing (external daemon without hook).
    """
    if _daemon_running():
        if not _hook_known_registered():
            print("Restarting aria2c to register completion hook...")
            _kill_aria2c()
            _start_daemon()
    else:
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)
        print("Starting aria2c daemon...")
        _start_daemon()

    if not _daemon_running():
        raise RuntimeError("aria2c daemon failed to start.")


def add_download(target: str, download_path: str):
    ensure_daemon()
    target = target.strip("'\" \t\r\n")
    if not target:
        raise ValueError("No magnet link or torrent file path provided.")

    expanded_path = os.path.abspath(os.path.expanduser(target))
    dl_options = {
        "dir": str(download_path),
        "seed-time": "0",
    }

    if os.path.isfile(expanded_path):
        import base64
        with open(expanded_path, "rb") as f:
            torrent_b64 = base64.b64encode(f.read()).decode("utf-8")
        response = _rpc("aria2.addTorrent", [torrent_b64, [], dl_options])
    elif target.startswith("magnet:") or target.startswith("http://") or target.startswith("https://") or target.startswith("ftp://"):
        response = _rpc("aria2.addUri", [[target], dl_options])
    else:
        if target.endswith(".torrent") or "/" in target or "\\" in target or os.path.exists(os.path.dirname(expanded_path)):
            raise FileNotFoundError(f"Torrent file not found: '{target}'")
        response = _rpc("aria2.addUri", [[target], dl_options])

    gid = response.get("result", "?")
    print(f"Added download: {gid}")
    return gid


def get_active_downloads() -> list:
    """Return a list of active download names."""
    try:
        response = _rpc("aria2.tellActive")
        downloads = response.get("result", [])
        return [
            {
                "gid": d["gid"],
                "name": d.get("bittorrent", {}).get("info", {}).get("name", d["gid"]),
                "progress": round(int(d.get("completedLength", 0)) / max(int(d.get("totalLength", 1)), 1) * 100, 1),
                "speed": int(d.get("downloadSpeed", 0)),
                "peers": d.get("numSeeders", "?"),
                "status": d.get("status", "active"),
            }
            for d in downloads
        ]
    except Exception:
        return []
