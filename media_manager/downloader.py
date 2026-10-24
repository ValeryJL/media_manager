import subprocess
import time
import os
import sys
import json
import shutil
import struct
import urllib.request
from pathlib import Path
from .config import get_config_dir, get_base_dir, get_public_dir, load_config

TRACKERS = ",".join([
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://9.rarbg.com:2810/announce",
    "udp://tracker.torrent.eu.org:451/announce"
])

_CONFIG_DIR  = os.path.normpath(str(get_config_dir()))
_RPC_URL     = "http://localhost:6800/jsonrpc"
_STATE_FILE  = os.path.join(_CONFIG_DIR, ".hook_registered")


def get_hook_path() -> str:
    """Return the absolute path to the event hook script/executable."""
    cfg_dir = os.path.normpath(str(get_config_dir()))
    if os.name == "nt":
        return os.path.join(cfg_dir, "hook.bat")
    return os.path.join(cfg_dir, "hook.sh")


def get_session_path() -> str:
    """Return the path to the persistent aria2c session file."""
    cfg_dir = os.path.normpath(str(get_config_dir()))
    os.makedirs(cfg_dir, exist_ok=True)
    session_file = os.path.join(cfg_dir, "aria2.session")
    if not os.path.exists(session_file):
        with open(session_file, "w", encoding="utf-8") as f:
            f.write("")
    if os.name != "nt" and get_base_dir() == get_public_dir():
        try:
            os.chmod(cfg_dir, 0o777)
            os.chmod(session_file, 0o666)
        except Exception:
            pass
    return session_file


_HOOK_SCRIPT = get_hook_path()


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


def _register_windows_autostart():
    """Register a silent logon entry in HKCU Run so incomplete downloads resume automatically on user login."""
    if os.name != "nt":
        return
    try:
        import winreg
        py_exe = sys.executable
        dir_name = os.path.dirname(py_exe)
        pyw_exe = os.path.join(dir_name, "pythonw.exe")
        runner = pyw_exe if os.path.exists(pyw_exe) else py_exe
        cmd = f'"{runner}" -c "from media_manager.downloader import ensure_daemon; ensure_daemon()"'
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "MediaManagerDaemon", 0, winreg.REG_SZ, cmd)
    except Exception:
        pass


def get_aria2c_binary() -> str:
    """Locate the aria2c binary, checking shared/local bin directories and Windows Registry PATH."""
    if os.name == "nt":
        _refresh_windows_path()

    # Check shared/local bin directories first (e.g. C:\Users\Public\.local\bin)
    exe_name = "aria2c.exe" if os.name == "nt" else "aria2c"
    for base in (get_base_dir(), get_public_dir(), Path.home()):
        candidate = base / ".local" / "bin" / exe_name
        if candidate.is_file():
            return str(candidate)

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
    cfg_dir = os.path.normpath(str(get_config_dir()))
    os.makedirs(cfg_dir, exist_ok=True)
    py_exe = sys.executable
    if os.name == "nt":
        # Remove legacy hook.exe if present to avoid Windows App Control (Smart App Control / WDAC) violations
        old_hook_exe = os.path.join(cfg_dir, "hook.exe")
        if os.path.exists(old_hook_exe):
            try:
                os.remove(old_hook_exe)
            except Exception:
                pass

        bat_path = os.path.join(cfg_dir, "hook.bat")
        dir_name = os.path.dirname(py_exe)
        pyw_exe = os.path.join(dir_name, "pythonw.exe")
        runner = pyw_exe if os.path.exists(pyw_exe) else py_exe
        content = f'@echo off\r\nstart "" /B "{runner}" -m media_manager.cli hook "%~1" "%~2" "%~3"\r\n'
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(content)
        return bat_path
    else:
        hook_path = os.path.join(cfg_dir, "hook.sh")
        umask_line = "umask 0000\n" if get_base_dir() == get_public_dir() else ""
        content = f'#!/usr/bin/env bash\n{umask_line}"{py_exe}" -m media_manager.cli hook "$1" "$2" "$3"\n'
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
    try:
        data = _rpc("aria2.getGlobalOption")
        opts = data.get("result", {})
        expected_hook = os.path.normcase(os.path.abspath(get_hook_path()))
        current_hook = os.path.normcase(os.path.abspath(opts.get("on-download-complete") or ""))
        current_bt_hook = os.path.normcase(os.path.abspath(opts.get("on-bt-download-complete") or ""))
        has_save_session = bool(opts.get("save-session"))
        return current_hook == expected_hook and current_bt_hook == expected_hook and has_save_session
    except Exception:
        return False


def _kill_aria2c():
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
        subprocess.run(["taskkill", "/F", "/IM", "aria2c.exe"], capture_output=True, creationflags=flags)
    else:
        subprocess.run(["killall", "aria2c"], capture_output=True)
    time.sleep(1.0)


def _extract_infohash_from_aria2_file(aria2_path: Path) -> str:
    """Extract the 20-byte BitTorrent SHA-1 infoHash from an aria2 control file (.aria2)."""
    try:
        with open(aria2_path, "rb") as f:
            header = f.read(32)
        if len(header) < 10:
            return ""
        ver, ext, ih_len = struct.unpack(">HII", header[:10])
        if (ext & 1) and ih_len == 20 and len(header) >= 30:
            return header[10:30].hex().lower()
    except Exception:
        pass
    return ""


def recover_incomplete_downloads():
    """
    Scan download_path for orphaned .aria2 control files (e.g. from another user's closed session)
    and automatically resume them in the running aria2c daemon.
    """
    try:
        config = load_config()
        dl_dir = Path(config["download_path"])
        if not dl_dir.exists():
            return

        active = _rpc("aria2.tellActive").get("result", [])
        waiting = _rpc("aria2.tellWaiting", [0, 100]).get("result", [])
        known_hashes = {
            (d.get("infoHash") or "").lower()
            for d in (active + waiting)
            if d.get("infoHash")
        }

        added = False
        for aria2_file in dl_dir.glob("*.aria2"):
            infohash = _extract_infohash_from_aria2_file(aria2_file)
            if infohash and infohash not in known_hashes:
                magnet = f"magnet:?xt=urn:btih:{infohash}"
                dl_options = {
                    "dir": str(dl_dir),
                    "seed-time": "0",
                    "continue": "true",
                }
                _rpc("aria2.addUri", [[magnet], dl_options])
                known_hashes.add(infohash)
                added = True
        if added:
            try:
                _rpc("aria2.saveSession")
            except Exception:
                pass
    except Exception:
        pass


def _start_daemon():
    hook_path = create_hook_script()
    session_path = get_session_path()
    aria2_bin = get_aria2c_binary()
    args = [
        aria2_bin,
        "--enable-rpc",
        "--rpc-listen-all=false",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--continue=true",
        "--seed-time=0",
        f"--bt-tracker={TRACKERS}",
        f"--input-file={session_path}",
        f"--save-session={session_path}",
        "--save-session-interval=5",
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
    state_file = os.path.join(os.path.normpath(str(get_config_dir())), ".hook_registered")
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("ok\n")


def ensure_daemon():
    """
    Ensure aria2c is running with the hook and session persistence registered,
    and recover any incomplete downloads left by another user session.
    """
    _register_windows_autostart()
    if _daemon_running():
        if not _hook_known_registered():
            print("Restarting aria2c to register background hook...")
            _kill_aria2c()
            _start_daemon()
    else:
        state_file = os.path.join(os.path.normpath(str(get_config_dir())), ".hook_registered")
        if os.path.exists(state_file):
            os.remove(state_file)
        print("Starting aria2c daemon...")
        _start_daemon()

    if not _daemon_running():
        raise RuntimeError("aria2c daemon failed to start.")

    recover_incomplete_downloads()


def add_download(target: str, download_path: str):
    ensure_daemon()
    target = target.strip("'\" \t\r\n")
    if not target:
        raise ValueError("No magnet link or torrent file path provided.")

    expanded_path = os.path.abspath(os.path.expanduser(target))
    dl_options = {
        "dir": str(download_path),
        "seed-time": "0",
        "continue": "true",
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

    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass

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
