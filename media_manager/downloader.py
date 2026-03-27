import subprocess
import time
import os
import json

TRACKERS = ",".join([
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://9.rarbg.com:2810/announce",
    "udp://tracker.torrent.eu.org:451/announce"
])

_CONFIG_DIR  = os.path.expanduser("~/.config/media_manager")
_HOOK_SCRIPT = os.path.join(_CONFIG_DIR, "hook.sh")
_STATE_FILE  = os.path.join(_CONFIG_DIR, ".hook_registered")
_RPC_URL     = "http://localhost:6800/jsonrpc"


def _rpc(method: str, params=None) -> dict:
    """Send a JSON-RPC request to aria2c via curl. Fast and reliable."""
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": "mm"})
    result = subprocess.run(
        ["curl", "-sf", "-m", "5", "-d", payload, _RPC_URL],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise ConnectionError(f"aria2c RPC call failed: {result.stderr}")
    return json.loads(result.stdout)


def create_hook_script() -> str:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    venv_bin = os.path.expanduser("~/.local/share/media_manager/venv/bin/media-manager")
    executable = venv_bin if os.path.exists(venv_bin) else "media-manager"
    content = f"#!/usr/bin/env bash\n{executable} hook \"$1\" \"$2\" \"$3\"\n"
    with open(_HOOK_SCRIPT, "w") as f:
        f.write(content)
    os.chmod(_HOOK_SCRIPT, 0o755)
    return _HOOK_SCRIPT


def _daemon_running() -> bool:
    try:
        _rpc("aria2.getVersion")
        return True
    except Exception:
        return False


def _hook_known_registered() -> bool:
    return os.path.exists(_STATE_FILE)


def _kill_aria2c():
    subprocess.run(["killall", "aria2c"], capture_output=True)
    time.sleep(1.0)


def _start_daemon():
    hook_path = create_hook_script()
    subprocess.Popen(
        [
            "aria2c",
            "--enable-rpc",
            "--rpc-listen-all=false",
            "--daemon",
            "--enable-dht=true",
            "--bt-enable-lpd=true",
            "--enable-peer-exchange=true",
            f"--bt-tracker={TRACKERS}",
            f"--on-download-complete={hook_path}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait up to 5 seconds for the daemon to respond
    for _ in range(10):
        time.sleep(0.5)
        if _daemon_running():
            break
    with open(_STATE_FILE, "w") as f:
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


def add_download(uri: str, download_path: str):
    ensure_daemon()
    response = _rpc("aria2.addUri", [[uri], {"dir": str(download_path)}])
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
