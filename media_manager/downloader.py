import subprocess
import time
import os
import sys
import json
import shutil
import struct
import urllib.request
import urllib.error
import urllib.parse
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


def get_history_path() -> str:
    """Return the path to the persistent completed downloads history file."""
    cfg_dir = os.path.normpath(str(get_config_dir()))
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "completed_history.json")


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
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            data = json.loads(err_body)
        except Exception:
            raise ConnectionError(f"aria2c RPC HTTP error: {e}")
        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            raise RuntimeError(f"aria2c error: {err_msg}")
        raise ConnectionError(f"aria2c RPC HTTP error: {e}")
    except Exception as e:
        raise ConnectionError(f"aria2c RPC connection failed: {e}")
    if "error" in data:
        err_msg = data["error"].get("message", str(data["error"]))
        raise RuntimeError(f"aria2c error: {err_msg}")
    return data


def format_size(num_bytes: int | float) -> str:
    """Format a byte count into a human-readable string (B, KB, MB, GB, TB)."""
    try:
        val = float(num_bytes)
    except (ValueError, TypeError):
        return "0 B"
    if val < 0:
        val = 0.0
    if val < 1024:
        return f"{int(val)} B"
    elif val < 1024 ** 2:
        return f"{val / 1024:.1f} KB"
    elif val < 1024 ** 3:
        return f"{val / (1024 ** 2):.2f} MB"
    elif val < 1024 ** 4:
        return f"{val / (1024 ** 3):.2f} GB"
    else:
        return f"{val / (1024 ** 4):.2f} TB"


def format_speed(bps: int | float) -> str:
    """Format a transfer speed in bytes/sec into a human-readable string."""
    try:
        val = float(bps)
    except (ValueError, TypeError):
        return "0 B/s"
    if val <= 0:
        return "0 B/s"
    return f"{format_size(val)}/s"


def format_eta(remaining_bytes: int | float, speed_bps: int | float) -> str:
    """Format estimated time remaining given remaining bytes and current download speed."""
    try:
        rem = float(remaining_bytes)
        spd = float(speed_bps)
    except (ValueError, TypeError):
        return "∞"
    if rem <= 0:
        return "0s"
    if spd <= 0:
        return "∞"
    seconds = int(rem / spd)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    elif seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    else:
        return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


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
        waiting = _rpc("aria2.tellWaiting", [0, 1000]).get("result", [])
        stopped = _rpc("aria2.tellStopped", [0, 1000]).get("result", [])
        known_hashes = {
            (d.get("infoHash") or "").lower()
            for d in (active + waiting + stopped)
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


def ensure_daemon(quiet: bool = False):
    """
    Ensure aria2c is running with the hook and session persistence registered,
    and recover any incomplete downloads left by another user session.
    """
    _register_windows_autostart()
    if _daemon_running():
        if not _hook_known_registered():
            if not quiet:
                print("Restarting aria2c to register background hook...")
            _kill_aria2c()
            _start_daemon()
    else:
        state_file = os.path.join(os.path.normpath(str(get_config_dir())), ".hook_registered")
        if os.path.exists(state_file):
            os.remove(state_file)
        if not quiet:
            print("Starting aria2c daemon...")
        _start_daemon()

    if not _daemon_running():
        raise RuntimeError("aria2c daemon failed to start.")

    recover_incomplete_downloads()


def add_download(target: str, download_path: str, quiet: bool = False):
    ensure_daemon(quiet=quiet)
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
    if not quiet:
        print(f"Added download: {gid}")
    return gid


def _extract_download_name(d: dict) -> str:
    """Extract a clean, human-readable name from an aria2 download status dictionary."""
    if d.get("name"):
        return str(d["name"])

    bt_info = d.get("bittorrent", {}).get("info", {})
    if bt_info and bt_info.get("name"):
        return str(bt_info["name"])

    files = d.get("files", [])
    if files:
        first_path = files[0].get("path", "")
        if first_path:
            if first_path.startswith("[METADATA]"):
                meta_title = first_path[len("[METADATA]"):].strip()
                return f"[Metadatos] {meta_title}" if meta_title else first_path
            dl_dir = d.get("dir", "")
            if dl_dir:
                try:
                    rel = Path(first_path).resolve().relative_to(Path(dl_dir).resolve())
                    if rel.parts:
                        return rel.parts[0]
                except Exception:
                    pass
            return Path(first_path).name

        uris = files[0].get("uris", [])
        if uris and uris[0].get("uri"):
            uri = uris[0]["uri"]
            if uri.startswith("magnet:?"):
                parsed = urllib.parse.parse_qs(uri[8:])
                dn = parsed.get("dn", [None])[0]
                if dn:
                    return f"[Metadatos] {urllib.parse.unquote_plus(dn)}"
            else:
                path_part = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
                if path_part and Path(path_part).name:
                    return Path(path_part).name

    info_hash = d.get("infoHash") or d.get("info_hash")
    if info_hash:
        return f"[Magnet] {info_hash}"

    return f"Download {d.get('gid', '?')}"


def _load_completed_history() -> list:
    """Load persistent completed downloads history from disk."""
    hist_path = get_history_path()
    if not os.path.exists(hist_path):
        return []
    try:
        with open(hist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_completed_history(items: list):
    """Save persistent completed downloads history to disk."""
    hist_path = get_history_path()
    try:
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def record_completed_download(gid: str, path: str = ""):
    """
    Record a completed download into completed_history.json so it remains visible
    in the download viewer until the user clears completed downloads.
    """
    try:
        d = {}
        try:
            d = _rpc("aria2.tellStatus", [gid]).get("result", {})
        except Exception:
            pass

        raw_first_path = ""
        if d.get("files"):
            raw_first_path = d["files"][0].get("path", "")
        if d.get("followedBy") or raw_first_path.startswith("[METADATA]"):
            # Do not record internal magnet metadata resolution steps as completed downloads
            return

        name = _extract_download_name(d) if d else ""
        total_length = int(d.get("totalLength", 0)) if d else 0
        info_hash = (d.get("infoHash") or "").lower() if d else ""
        dl_dir = d.get("dir", "") if d else ""

        if path:
            try:
                config = load_config()
                cfg_dl_dir = Path(config["download_path"]).resolve()
                item_path = Path(path).resolve()
                try:
                    rel_path = item_path.relative_to(cfg_dl_dir)
                    top_item = cfg_dl_dir / rel_path.parts[0]
                except ValueError:
                    top_item = item_path

                if (not name or name.startswith("Download ")) and top_item.name:
                    name = top_item.name
                if total_length <= 0 and top_item.exists():
                    if top_item.is_file():
                        total_length = top_item.stat().st_size
                    elif top_item.is_dir():
                        total_length = sum(
                            f.stat().st_size for f in top_item.rglob("*")
                            if f.is_file() and not f.name.endswith(".aria2")
                        )
            except Exception:
                pass

        if not name or name.startswith("[Metadatos]"):
            return

        history = _load_completed_history()
        # Update existing or append
        updated = False
        entry = {
            "gid": gid,
            "name": name,
            "totalLength": str(total_length),
            "completedLength": str(total_length),
            "status": "complete",
            "infoHash": info_hash,
            "dir": dl_dir,
            "completedAt": time.time(),
        }
        for i, existing in enumerate(history):
            if existing.get("gid") == gid or (info_hash and existing.get("infoHash") == info_hash) or existing.get("name") == name:
                history[i] = entry
                updated = True
                break
        if not updated:
            history.append(entry)
        _save_completed_history(history)
    except Exception:
        pass


def _normalize_download(d: dict, from_history: bool = False) -> dict:
    """Normalize a raw aria2 status dict into a rich dictionary for the TUI and CLI."""
    gid = str(d.get("gid", "?"))
    status = str(d.get("status", "active")).lower()
    total_length = int(d.get("totalLength", 0) or 0)
    completed_length = int(d.get("completedLength", 0) or 0)
    if status == "complete" and total_length > 0 and completed_length < total_length:
        completed_length = total_length

    speed = int(d.get("downloadSpeed", 0) or 0)
    upload_speed = int(d.get("uploadSpeed", 0) or 0)

    if status == "complete":
        progress = 100.0
    elif total_length > 0:
        progress = min(100.0, round((completed_length / total_length) * 100, 1))
    else:
        progress = 0.0

    name = _extract_download_name(d)
    raw_first_path = ""
    if d.get("files"):
        raw_first_path = d["files"][0].get("path", "")
    is_metadata = (
        raw_first_path.startswith("[METADATA]")
        or name.startswith("[Metadatos]")
        or (bool(d.get("infoHash")) and total_length == 0 and not d.get("bittorrent", {}).get("info"))
    )

    seeders_raw = d.get("numSeeders")
    seeders = int(seeders_raw) if seeders_raw is not None and str(seeders_raw).isdigit() else 0
    connections_raw = d.get("connections")
    connections = int(connections_raw) if connections_raw is not None and str(connections_raw).isdigit() else 0

    remaining = max(0, total_length - completed_length)
    eta = format_eta(remaining, speed) if status == "active" and not is_metadata else "-"

    completed_size_str = format_size(completed_length)
    total_size_str = format_size(total_length) if total_length > 0 else ("Metadatos..." if is_metadata else "0 B")

    if status == "complete" and total_length > 0:
        size_str = f"{total_size_str} / {total_size_str}"
    elif total_length > 0:
        size_str = f"{completed_size_str} / {total_size_str}"
    elif is_metadata:
        size_str = "Metadatos..."
    else:
        size_str = completed_size_str

    return {
        "gid": gid,
        "name": name,
        "status": status,
        "is_active": status == "active",
        "is_metadata": is_metadata,
        "total_length": total_length,
        "completed_length": completed_length,
        "progress": progress,
        "speed": speed,
        "upload_speed": upload_speed,
        "speed_str": format_speed(speed),
        "upload_speed_str": format_speed(upload_speed),
        "seeders": seeders,
        "connections": connections,
        "peers": seeders if seeders > 0 else connections,
        "eta": eta,
        "size_str": size_str,
        "completed_size_str": completed_size_str,
        "total_size_str": total_size_str,
        "info_hash": (d.get("infoHash") or "").lower(),
        "dir": d.get("dir", ""),
        "error_code": d.get("errorCode", ""),
        "error_message": d.get("errorMessage", ""),
        "following": d.get("following", ""),
        "followed_by": d.get("followedBy", []),
        "from_history": from_history,
    }


def get_all_downloads() -> list:
    """
    Return a unified list of all downloads (active, paused, waiting, complete, error)
     combining live aria2c RPC data with persistent completed history.
    """
    try:
        res = _rpc("system.multicall", [[
            {"methodName": "aria2.tellActive"},
            {"methodName": "aria2.tellWaiting", "params": [0, 1000]},
            {"methodName": "aria2.tellStopped", "params": [0, 1000]},
        ]]).get("result", [])
        active_raw = res[0][0] if len(res) > 0 and isinstance(res[0], list) and res[0] else []
        waiting_raw = res[1][0] if len(res) > 1 and isinstance(res[1], list) and res[1] else []
        stopped_raw = res[2][0] if len(res) > 2 and isinstance(res[2], list) and res[2] else []
    except Exception:
        active_raw, waiting_raw, stopped_raw = [], [], []

    all_live_gids = {
        d.get("gid") for d in (active_raw + waiting_raw + stopped_raw) if d.get("gid")
    }

    normalized = []
    seen_gids = set()
    seen_hashes = set()
    seen_names = set()

    for d in active_raw + waiting_raw:
        item = _normalize_download(d, from_history=False)
        normalized.append(item)
        seen_gids.add(item["gid"])
        if item["info_hash"]:
            seen_hashes.add(item["info_hash"])
        seen_names.add(item["name"])

    history = _load_completed_history()
    history_changed = False

    for d in stopped_raw:
        status = str(d.get("status", "")).lower()
        # Skip removed downloads
        if status == "removed":
            continue
        # Skip completed [METADATA] phase items that were followed by the real torrent download
        followed_by = d.get("followedBy", [])
        first_path = d.get("files", [{}])[0].get("path", "") if d.get("files") else ""
        if status == "complete" and (followed_by or first_path.startswith("[METADATA]")):
            continue
        if followed_by and any(fg in all_live_gids for fg in followed_by):
            continue

        item = _normalize_download(d, from_history=False)
        normalized.append(item)
        seen_gids.add(item["gid"])
        if item["info_hash"]:
            seen_hashes.add(item["info_hash"])
        seen_names.add(item["name"])

        # Sync completed downloads into persistent history
        if status == "complete" and not item["is_metadata"]:
            already_saved = any(
                h.get("gid") == item["gid"]
                or (item["info_hash"] and h.get("infoHash") == item["info_hash"])
                or h.get("name") == item["name"]
                for h in history
            )
            if not already_saved:
                history.append({
                    "gid": item["gid"],
                    "name": item["name"],
                    "totalLength": str(item["total_length"]),
                    "completedLength": str(item["completed_length"]),
                    "status": "complete",
                    "infoHash": item["info_hash"],
                    "dir": item["dir"],
                    "completedAt": time.time(),
                })
                history_changed = True

    if history_changed:
        _save_completed_history(history)

    # Append completed items from persistent history that are not already in live results
    for h in history:
        h_gid = str(h.get("gid", ""))
        h_hash = (h.get("infoHash") or "").lower()
        h_name = str(h.get("name", ""))
        if h_gid in seen_gids:
            continue
        if h_hash and h_hash in seen_hashes:
            continue
        if h_name and h_name in seen_names:
            continue
        item = _normalize_download(h, from_history=True)
        normalized.append(item)
        seen_gids.add(item["gid"])

    return normalized


def get_active_downloads() -> list:
    """Return a list of active downloads (kept for backwards compatibility)."""
    return [d for d in get_all_downloads() if d["status"] == "active"]


def pause_download(gid: str) -> bool:
    """Pause an active or waiting download immediately."""
    try:
        _rpc("aria2.forcePause", [gid])
    except Exception:
        _rpc("aria2.pause", [gid])
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass
    return True


def resume_download(gid: str) -> bool:
    """Resume a paused download."""
    _rpc("aria2.unpause", [gid])
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass
    return True


def toggle_pause_download(gid: str) -> str:
    """
    Toggle a download between active and paused states.
    Returns the new state ('paused' or 'active').
    """
    info = _rpc("aria2.tellStatus", [gid, ["gid", "status"]]).get("result", {})
    status = str(info.get("status", "")).lower()
    if status in ("active", "waiting"):
        pause_download(gid)
        return "paused"
    elif status == "paused":
        resume_download(gid)
        return "active"
    return status


def pause_all_downloads() -> bool:
    """Pause all active/waiting downloads immediately."""
    try:
        _rpc("aria2.forcePauseAll")
    except Exception:
        _rpc("aria2.pauseAll")
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass
    return True


def resume_all_downloads() -> bool:
    """Resume all paused downloads."""
    _rpc("aria2.unpauseAll")
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass
    return True


def _safe_delete_path(target: Path, retries: int = 6, delay: float = 0.15):
    """Safely delete a file or directory with retries for Windows file handle release."""
    for _ in range(retries):
        if not target.exists():
            return
        try:
            if target.is_dir():
                shutil.rmtree(str(target))
            else:
                target.unlink()
            return
        except Exception:
            time.sleep(delay)


def remove_download(gid: str, delete_files: bool = True) -> bool:
    """
    Remove a specific download by GID from aria2c (and completed history).
    If the download was incomplete and delete_files=True, also deletes its .aria2 control
    file and partial data in download_path so it is not resurrected on next daemon check.
    """
    info = {}
    try:
        info = _rpc("aria2.tellStatus", [gid]).get("result", {})
    except Exception:
        pass

    status = str(info.get("status", "")).lower()
    info_hash = (info.get("infoHash") or "").lower()
    following = info.get("following", "")
    bt_name = info.get("bittorrent", {}).get("info", {}).get("name", "")
    files = info.get("files", [])

    try:
        config = load_config()
        dl_dir = Path(info.get("dir") or config["download_path"]).resolve()
    except Exception:
        dl_dir = None

    # 1. If active, waiting, or paused, force remove from active queue
    if status in ("active", "waiting", "paused"):
        try:
            _rpc("aria2.forceRemove", [gid])
        except Exception:
            try:
                _rpc("aria2.remove", [gid])
            except Exception:
                pass

        # Wait up to 1s for aria2c to transition the GID to removed and release file locks
        for _ in range(10):
            try:
                st = _rpc("aria2.tellStatus", [gid, ["status"]]).get("result", {}).get("status", "")
                if st in ("removed", "error", "complete", ""):
                    break
            except Exception:
                break
            time.sleep(0.1)

    # 2. Remove from aria2c stopped results
    try:
        _rpc("aria2.removeDownloadResult", [gid])
    except Exception:
        pass

    if following:
        try:
            _rpc("aria2.removeDownloadResult", [following])
        except Exception:
            pass

    # 3. Remove from persistent completed history if present
    history = _load_completed_history()
    new_history = [
        h for h in history
        if str(h.get("gid")) != str(gid) and (not info_hash or h.get("infoHash") != info_hash)
    ]
    if len(new_history) != len(history):
        _save_completed_history(new_history)

    # 4. Save aria2 session immediately so removed download is not persisted in aria2.session
    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass

    # 5. Clean up .aria2 control files and partial files for incomplete downloads
    if delete_files and status != "complete" and dl_dir and dl_dir.exists():
        # Match by infoHash in .aria2 files
        if info_hash:
            for aria2_file in list(dl_dir.glob("*.aria2")):
                if _extract_infohash_from_aria2_file(aria2_file) == info_hash:
                    stem_target = dl_dir / aria2_file.stem
                    _safe_delete_path(aria2_file)
                    if stem_target.exists() and stem_target.resolve() != dl_dir:
                        _safe_delete_path(stem_target)

        # Match by BitTorrent name
        if bt_name:
            candidate = (dl_dir / bt_name).resolve()
            candidate_aria2 = Path(str(candidate) + ".aria2")
            if candidate_aria2.exists():
                _safe_delete_path(candidate_aria2)
            if candidate.exists() and candidate != dl_dir and dl_dir in candidate.parents:
                _safe_delete_path(candidate)

        # Match by file paths reported by aria2
        for f_entry in files:
            fpath_str = f_entry.get("path", "")
            if not fpath_str or fpath_str.startswith("[METADATA]"):
                continue
            try:
                fpath = Path(fpath_str).resolve()
                rel = fpath.relative_to(dl_dir)
                if rel.parts:
                    top_item = dl_dir / rel.parts[0]
                    top_aria2 = Path(str(top_item) + ".aria2")
                    if top_aria2.exists():
                        _safe_delete_path(top_aria2)
                    if top_item.exists() and top_item != dl_dir:
                        _safe_delete_path(top_item)
            except Exception:
                pass

    return True


def clear_completed_downloads() -> int:
    """
    Purge all completed/stopped downloads from aria2c and clear persistent completed history.
    Returns the number of cleared downloads.
    """
    cleared_count = 0
    try:
        stopped = _rpc("aria2.tellStopped", [0, 1000]).get("result", [])
        for d in stopped:
            st = str(d.get("status", "")).lower()
            gid = d.get("gid")
            if st in ("complete", "removed", "error") and gid:
                try:
                    _rpc("aria2.removeDownloadResult", [gid])
                    if st == "complete":
                        cleared_count += 1
                except Exception:
                    pass
        try:
            _rpc("aria2.purgeDownloadResult")
        except Exception:
            pass
    except Exception:
        pass

    history = _load_completed_history()
    if history:
        cleared_count = max(cleared_count, len(history))
        _save_completed_history([])

    try:
        _rpc("aria2.saveSession")
    except Exception:
        pass

    return cleared_count
