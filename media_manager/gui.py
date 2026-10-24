import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
import yaml

# When launched via pythonw.exe on Windows, sys.stdout and sys.stderr are None.
# Redirect them to os.devnull so libraries never fail on stream writes.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from .config import get_base_dir, get_config_dir, get_public_dir, load_config
from .downloader import (
    _daemon_running,
    _kill_aria2c,
    _start_daemon,
    add_download,
    clear_completed_downloads,
    ensure_daemon,
    format_size,
    format_speed,
    get_all_downloads,
    pause_all_downloads,
    remove_download,
    resume_all_downloads,
    toggle_pause_download,
)
from .organizer import MEDIA_EXTENSIONS, organize_downloads
from .tui import _parse_size_to_bytes, get_pirate_command


# ---------------------------------------------------------------------------
# Color Palettes — Neutral Steel & Slate (Zero Violet/Purple)
# Fixed Top Bar & Sidebar in Steel-Slate (#323943) that contrasts with both
# Dark Mode (#21252B) and Light Mode (#F3F4F6).
# ---------------------------------------------------------------------------

SHELL_STYLE = {
    "topbar_bg": "#2B313A",       # Neutral dark steel top bar
    "sidebar_bg": "#323943",      # Neutral steel-slate sidebar (same in dark & light)
    "border": "#424B57",          # Subtle steel divider border
    "item_active_bg": "#404956",  # Active sidebar tab background
    "item_active_bar": "#6893B8", # Left indicator bar on active tab (calm steel blue)
    "text_primary": "#F0F3F6",    # Crisp off-white text
    "text_secondary": "#B4BEC8",  # Calm silver-gray inactive text
    "accent": "#6893B8",          # Muted Nord steel-blue
    "pill_bg": "#232830",         # Top bar status counter box
}

THEMES = {
    "dark": {
        "name": "dark",
        "bg_app": "#21252B",        # Neutral charcoal-slate workspace (not pitch black)
        "bg_card": "#282C34",       # Elevated card surface
        "bg_input": "#1D2025",      # Input field background
        "border": "#363B46",        # Subtle card/input border
        "text_primary": "#E6EAF0",  # Soft off-white
        "text_secondary": "#9DA5B4",# Calm neutral gray metadata
        "text_muted": "#6E7685",    # Muted captions
        "accent": "#5E81AC",        # Calm Nord steel-blue accent
        "complete": "#68A87A",      # Soft sage green
        "paused": "#7C8594",        # Muted slate gray
        "danger": "#CC6666",        # Muted brick red
        "progress_bg": "#1B1E23",
        "toast_bg": "#323842",
    },
    "light": {
        "name": "light",
        "bg_app": "#F3F4F6",        # Soft neutral cool-alabaster (not glaring white)
        "bg_card": "#FFFFFF",       # Clean card surface
        "bg_input": "#FFFFFF",      # Input field surface
        "border": "#D5D9E0",        # Subtle neutral border
        "text_primary": "#24292F",  # Soft charcoal text
        "text_secondary": "#57606A",# Neutral slate metadata
        "text_muted": "#8C959F",    # Muted captions
        "accent": "#4A729E",        # Calm steel-blue accent
        "complete": "#46895A",      # Soft forest-sage green
        "paused": "#8C959F",        # Muted gray
        "danger": "#B84C4C",        # Muted red
        "progress_bg": "#E5E8EC",
        "toast_bg": "#2B313A",
    },
}


# ---------------------------------------------------------------------------
# Supersampled 4x Antialiased App Icon & Cross-Platform System App Installer
# ---------------------------------------------------------------------------

def ensure_app_icons() -> tuple[str, str]:
    """
    Generate a minimalist geometric 'V' (Vale) monogram desktop icon in config_dir/assets.
    Rendered at 1024x1024 and Lanczos-downsampled to 256x256 for crisp vector-like edges.
    Returns (png_path, ico_path).
    """
    assets_dir = get_config_dir() / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    png_path = assets_dir / "media_manager_v4.png"
    ico_path = assets_dir / "media_manager_v4.ico"

    if png_path.exists() and ico_path.exists():
        return str(png_path), str(ico_path)

    try:
        from PIL import Image, ImageDraw

        S = 1024
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 1. Clean minimalist squircle tile (warm porcelain #F4F5F7 with subtle slate border)
        draw.rounded_rectangle(
            [(64, 64), (S - 64, S - 64)],
            radius=190,
            fill=(244, 245, 247, 255),
            outline=(212, 218, 226, 255),
            width=10,
        )

        # 2. Minimalist architectural "V" ribbon monogram (representing Vale + Downward/Media chevron)
        # Right wing (soft Nord steel-blue #5E81AC, receding behind at bottom)
        right_wing = [
            (632, 276),
            (768, 276),
            (564, 764),
            (428, 764),
        ]
        draw.polygon(right_wing, fill=(94, 129, 172, 255))

        # Subtle shadow at intersection
        overlap_shadow = [
            (460, 688),
            (564, 764),
            (428, 764),
        ]
        draw.polygon(overlap_shadow, fill=(72, 102, 140, 255))

        # Left wing (deep charcoal-slate #2B323C, foreground stroke)
        left_wing = [
            (256, 276),
            (392, 276),
            (564, 764),
            (428, 764),
        ]
        draw.polygon(left_wing, fill=(43, 50, 60, 255))

        # Minimalist floating accent dot above the V valley (clean geometric focal point)
        draw.ellipse(
            [(474, 276), (550, 352)],
            fill=(94, 129, 172, 255),
        )

        final_256 = img.resize((256, 256), resample=Image.Resampling.LANCZOS)
        final_256.save(str(png_path), format="PNG")
        final_256.save(
            str(ico_path),
            format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )
    except Exception:
        pass

    return str(png_path), str(ico_path)


def install_desktop_shortcut(all_users: bool = None) -> list[str]:
    """
    Install Media Manager as a native desktop application in the operating system:
    - Windows: Start Menu + Desktop .lnk shortcuts using pythonw.exe and custom .ico
    - Linux: .desktop launcher in /usr/share/applications or ~/.local/share/applications
    - macOS: /Applications/Media Manager.app (or ~/Applications/Media Manager.app) bundle
    Returns a list of created shortcut/launcher paths.
    """
    created = []
    png_path, ico_path = ensure_app_icons()
    base_dir = get_base_dir()
    if all_users is None:
        all_users = (base_dir == get_public_dir())

    py_exe = sys.executable
    py_dir = os.path.dirname(py_exe)
    pyw_exe = os.path.join(py_dir, "pythonw.exe")
    gui_runner = pyw_exe if (os.name == "nt" and os.path.exists(pyw_exe)) else py_exe

    if os.name == "nt":
        locations = []
        if all_users:
            prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
            locations.append(Path(prog_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Media Manager.lnk")
            pub_desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop" / "Media Manager.lnk"
            locations.append(pub_desktop)
        user_start = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Media Manager.lnk"
        user_desktop = Path.home() / "Desktop" / "Media Manager.lnk"
        locations.extend([user_start, user_desktop])

        for lnk_path in locations:
            try:
                lnk_path.parent.mkdir(parents=True, exist_ok=True)
                ps_script = (
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$s = $ws.CreateShortcut("{lnk_path}"); '
                    f'$s.TargetPath = "{gui_runner}"; '
                    f'$s.Arguments = "-m media_manager.gui"; '
                    f'$s.WorkingDirectory = "{base_dir}"; '
                    f'$s.Description = "Media Manager"; '
                    f'if (Test-Path "{ico_path}") {{ $s.IconLocation = "{ico_path}" }}; '
                    f'$s.Save()'
                )
                flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
                res = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True,
                    creationflags=flags,
                )
                if res.returncode == 0 and lnk_path.exists():
                    created.append(str(lnk_path))
            except Exception:
                pass

    elif sys.platform == "darwin":
        apps_dir = Path("/Applications") if all_users and os.access("/Applications", os.W_OK) else (Path.home() / "Applications")
        app_bundle = apps_dir / "Media Manager.app"
        macos_dir = app_bundle / "Contents" / "MacOS"
        res_dir = app_bundle / "Contents" / "Resources"
        try:
            macos_dir.mkdir(parents=True, exist_ok=True)
            res_dir.mkdir(parents=True, exist_ok=True)
            launcher = macos_dir / "Media Manager"
            launcher_content = (
                f'#!/usr/bin/env bash\n'
                f'export MEDIA_MANAGER_HOME="{base_dir}"\n'
                f'exec "{py_exe}" -m media_manager.gui "$@"\n'
            )
            launcher.write_text(launcher_content, encoding="utf-8")
            os.chmod(launcher, 0o755)

            plist_path = app_bundle / "Contents" / "Info.plist"
            plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Media Manager</string>
    <key>CFBundleDisplayName</key>
    <string>Media Manager</string>
    <key>CFBundleIdentifier</key>
    <string>org.mediamanager.app</string>
    <key>CFBundleVersion</key>
    <string>0.2.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>Media Manager</string>
    <key>CFBundleIconFile</key>
    <string>media_manager.png</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
            plist_path.write_text(plist_content, encoding="utf-8")
            if os.path.exists(png_path):
                import shutil
                shutil.copy2(png_path, res_dir / "media_manager.png")
            created.append(str(app_bundle))
        except Exception:
            pass

    else:
        desktop_entry = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=Media Manager\n"
            "Comment=Busca, descarga y organiza películas y series\n"
            f'Exec=env MEDIA_MANAGER_HOME="{base_dir}" "{py_exe}" -m media_manager.gui %U\n'
            f"Icon={png_path}\n"
            "Terminal=false\n"
            "Categories=AudioVideo;Video;Network;FileTransfer;P2P;\n"
            "MimeType=application/x-bittorrent;x-scheme-handler/magnet;\n"
            "StartupNotify=true\n"
        )
        targets = []
        if all_users and os.access("/usr/share/applications", os.W_OK):
            targets.append(Path("/usr/share/applications/media-manager.desktop"))
        targets.append(Path.home() / ".local" / "share" / "applications" / "media-manager.desktop")

        for desktop_path in targets:
            try:
                desktop_path.parent.mkdir(parents=True, exist_ok=True)
                desktop_path.write_text(desktop_entry, encoding="utf-8")
                os.chmod(desktop_path, 0o755)
                created.append(str(desktop_path))
            except Exception:
                pass

    return created


def spawn_gui_detached(initial_uri: str = None) -> bool:
    """
    Spawn the Flutter Desktop GUI as an independent background process (using pythonw.exe on Windows).
    """
    py_exe = sys.executable
    py_dir = os.path.dirname(py_exe)
    pyw_exe = os.path.join(py_dir, "pythonw.exe")
    runner = pyw_exe if (os.name == "nt" and os.path.exists(pyw_exe)) else py_exe

    cmd = [runner, "-m", "media_manager.gui"]
    if initial_uri:
        cmd.append(initial_uri)

    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
            )
        else:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helper functions for Library & Search in the GUI
# ---------------------------------------------------------------------------

def _search_torrents_sync(query_str: str) -> tuple[list, str]:
    """Run pirate-get in a background thread without blocking the UI."""
    pirate_cmd = get_pirate_command()
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        result = subprocess.run(
            [*pirate_cmd, query_str, "-j"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            **popen_kwargs,
        )
    except subprocess.CalledProcessError:
        return [], f"No se encontraron resultados para '{query_str}'."
    except Exception as e:
        return [], f"Error al ejecutar búsqueda: {e}"

    try:
        json_res = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], f"No se encontraron resultados para '{query_str}'."

    if not json_res:
        return [], f"No se encontraron resultados para '{query_str}'."

    items = []
    for entry in json_res:
        magnet = entry.get("magnet", "")
        if not magnet:
            continue
        size_str = str(entry.get("size", "0 B"))
        seeds = int(entry.get("seeders", 0) or 0)
        leeches = int(entry.get("leechers", 0) or 0)
        items.append(
            {
                "name": str(entry.get("name", "Unknown")),
                "size": size_str,
                "size_bytes": _parse_size_to_bytes(size_str),
                "seeders": seeds,
                "leechers": leeches,
                "uploaded": str(entry.get("uploaded", "-")),
                "magnet": magnet,
            }
        )
    return items, ""


def _scan_media_library(media_path_str: str) -> dict:
    """Scan Movies/ and Shows/ inside media_path to display in the Library tab."""
    root = Path(media_path_str)
    movies_dir = root / "Movies"
    shows_dir = root / "Shows"
    movies = []
    shows = []

    if movies_dir.exists():
        for item in sorted(movies_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                video_files = [
                    f for f in item.rglob("*")
                    if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
                ]
                total_sz = sum(f.stat().st_size for f in video_files) if video_files else 0
                movies.append(
                    {
                        "title": item.name,
                        "files_count": len(video_files),
                        "size_str": format_size(total_sz),
                        "path": str(item),
                    }
                )
            elif item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
                movies.append(
                    {
                        "title": item.stem,
                        "files_count": 1,
                        "size_str": format_size(item.stat().st_size),
                        "path": str(item.parent),
                    }
                )

    if shows_dir.exists():
        for show_dir in sorted(shows_dir.iterdir(), key=lambda p: p.name.lower()):
            if not show_dir.is_dir() or show_dir.name.startswith("."):
                continue
            seasons = [d for d in show_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
            episodes = [
                f for f in show_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
            ]
            total_sz = sum(f.stat().st_size for f in episodes) if episodes else 0
            shows.append(
                {
                    "title": show_dir.name,
                    "seasons_count": max(1, len(seasons)) if episodes else len(seasons),
                    "episodes_count": len(episodes),
                    "size_str": format_size(total_sz),
                    "path": str(show_dir),
                }
            )

    return {"movies": movies, "shows": shows}


def _open_folder_in_os(folder_path: str):
    """Open a directory in the native OS file explorer."""
    p = str(Path(folder_path).resolve())
    if not os.path.exists(p):
        return
    try:
        if os.name == "nt":
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


def _save_config_dict(cfg: dict):
    """Persist configuration dictionary to config.yml."""
    cfg_file = get_config_dir() / "config.yml"
    data = {
        "download_path": cfg["download_path"],
        "media_path": cfg["media_path"],
        "theme_mode": cfg.get("theme_mode", "dark"),
    }
    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Main Flet (Flutter Desktop) GUI Application
# ---------------------------------------------------------------------------

def launch_gui(initial_uri: str = None):
    """Launch the cross-platform Flutter Desktop application with neutral Top Bar + Sidebar."""
    import flet as ft

    png_icon, ico_icon = ensure_app_icons()

    try:
        ensure_daemon(quiet=True)
    except Exception:
        pass

    async def main(page: ft.Page):
        cfg = load_config()
        initial_theme_key = cfg.get("theme_mode", "dark")
        if initial_theme_key not in THEMES:
            initial_theme_key = "dark"

        page.title = "Media Manager"
        page.padding = 0
        page.spacing = 0
        page.window.width = 1060
        page.window.height = 680
        page.window.min_width = 840
        page.window.min_height = 540
        if os.name == "nt" and os.path.exists(ico_icon):
            page.window.icon = ico_icon
        elif os.path.exists(png_icon):
            page.window.icon = png_icon

        # Use neutral BLUE_GREY seed so Flutter never tints controls purple
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE_GREY)

        state = {
            "theme_key": initial_theme_key,
            "active_tab": 0,
            "order_gids": [],
            "downloads": [],
            "search_results": [],
            "search_checked": set(),
            "search_sort": "seeders",
            "is_searching": False,
            "search_status": "Ingresá un nombre para buscar torrents.",
            "library": {"movies": [], "shows": []},
            "config": cfg,
            "daemon_msg": "Motor aria2c activo en segundo plano",
            "running": True,
        }

        def T() -> dict:
            return THEMES[state["theme_key"]]

        # Rectangular button style helpers (radius=4, crisp angles, zero pills)
        def btn_primary_style(bg_col: str = None) -> ft.ButtonStyle:
            t = T()
            return ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=4),
                bgcolor=bg_col or t["accent"],
                color="#FFFFFF",
                padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            )

        def btn_outline_style() -> ft.ButtonStyle:
            t = T()
            return ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=4),
                side=ft.BorderSide(1, t["border"]),
                color=t["text_primary"],
                bgcolor=t["bg_card"],
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            )

        def btn_text_style() -> ft.ButtonStyle:
            t = T()
            return ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=4),
                color=t["text_secondary"],
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            )

        def btn_topbar_style() -> ft.ButtonStyle:
            return ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=4),
                side=ft.BorderSide(1, SHELL_STYLE["border"]),
                color=SHELL_STYLE["text_primary"],
                bgcolor=SHELL_STYLE["sidebar_bg"],
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            )

        def show_toast(msg: str, is_error: bool = False):
            t = T()
            sb = ft.SnackBar(
                content=ft.Text(msg, color="#FFFFFF", size=13),
                bgcolor=t["danger"] if is_error else t["toast_bg"],
                duration=2600,
            )
            page.show_dialog(sb)

        file_picker = ft.FilePicker()
        page.services.append(file_picker)

        # Persistent input controls
        magnet_input = ft.TextField(
            hint_text="Pegar enlace magnet o URL...",
            border_radius=4,
            height=38,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            text_size=13,
            expand=True,
        )

        search_input = ft.TextField(
            hint_text="Buscar película, serie o archivo...",
            border_radius=4,
            height=38,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            text_size=13,
            expand=True,
        )

        dl_path_field = ft.TextField(
            label="Carpeta de descargas temporales",
            value=state["config"]["download_path"],
            border_radius=4,
            text_size=13,
            expand=True,
        )

        media_path_field = ft.TextField(
            label="Carpeta de biblioteca (Movies / Shows)",
            value=state["config"]["media_path"],
            border_radius=4,
            text_size=13,
            expand=True,
        )

        # Dynamic controls
        topbar_stats_text = ft.Text("0 activas  ·  0 en pausa  ·  0 B/s", size=12, color=SHELL_STYLE["text_secondary"])
        subtitle_stats = ft.Text("", size=12.5)
        downloads_list_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        search_status_text = ft.Text(state["search_status"], size=12)
        search_results_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        download_selected_btn = ft.FilledButton(
            content="Descargar seleccionados (0)",
            height=36,
            visible=False,
        )
        movies_list_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        shows_list_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        lib_summary_text = ft.Text("", size=12.5)
        daemon_status_badge = ft.Text(state["daemon_msg"], size=13)

        root_container = ft.Container(expand=True)

        # ===================================================================
        # Action Handlers
        # ===================================================================

        async def on_add_magnet_click(e=None):
            val = (magnet_input.value or "").strip()
            if not val:
                return
            magnet_input.value = ""
            page.update()
            try:
                gid = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: add_download(val, state["config"]["download_path"], quiet=True)
                )
                show_toast(f"Descarga agregada ({gid})")
                await refresh_downloads_data()
            except Exception as ex:
                show_toast(f"No se pudo agregar: {ex}", is_error=True)

        magnet_input.on_submit = on_add_magnet_click

        async def on_pick_torrent_file(e):
            files = await file_picker.pick_files(
                dialog_title="Seleccionar archivo .torrent",
                allowed_extensions=["torrent"],
                allow_multiple=True,
            )
            if not files:
                return
            added = 0
            for f in files:
                if f.path:
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda p=f.path: add_download(p, state["config"]["download_path"], quiet=True)
                        )
                        added += 1
                    except Exception as ex:
                        show_toast(f"Error en {f.name}: {ex}", is_error=True)
            if added:
                show_toast(f"{added} archivo(s) .torrent agregado(s)")
                await refresh_downloads_data()

        async def on_pause_resume_all(e):
            dls = state["downloads"]
            if not dls:
                return
            has_active = any(d["status"] in ("active", "waiting") for d in dls)
            has_paused = any(d["status"] == "paused" for d in dls)
            try:
                if has_active:
                    await asyncio.get_running_loop().run_in_executor(None, pause_all_downloads)
                    show_toast("Descargas pausadas")
                elif has_paused:
                    await asyncio.get_running_loop().run_in_executor(None, resume_all_downloads)
                    show_toast("Descargas reanudadas")
                await refresh_downloads_data()
            except Exception as ex:
                show_toast(f"Error: {ex}", is_error=True)

        async def on_clear_completed(e):
            completed = [d for d in state["downloads"] if d["status"] == "complete"]
            if not completed:
                show_toast("No hay descargas completadas para limpiar")
                return
            try:
                await asyncio.get_running_loop().run_in_executor(None, clear_completed_downloads)
                show_toast(f"Se limpiaron {len(completed)} descarga(s)")
                await refresh_downloads_data()
            except Exception as ex:
                show_toast(f"Error: {ex}", is_error=True)

        async def on_organize_now(e):
            try:
                rep = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: organize_downloads(
                        state["config"]["download_path"],
                        state["config"]["media_path"],
                        quiet=True,
                    ),
                )
                moved_n = sum(1 for r in rep if r["status"] == "moved")
                if moved_n > 0:
                    show_toast(f"Se organizaron {moved_n} archivo(s) en la biblioteca")
                else:
                    show_toast("No hay descargas pendientes por organizar")
                await refresh_downloads_data()
                if state["active_tab"] == 2:
                    await refresh_library_view()
            except Exception as ex:
                show_toast(f"Error al organizar: {ex}", is_error=True)

        # ===================================================================
        # Builders for Download Cards, Search Rows, and Library Rows
        # ===================================================================

        def _build_download_card(d: dict) -> ft.Container:
            t = T()
            gid = d["gid"]
            status = d["status"]
            pct = max(0.0, min(100.0, float(d["progress"]))) / 100.0

            if status == "active":
                state_label = "Metadatos" if d["is_metadata"] else "Activo"
                bar_col = t["accent"]
                state_col = t["accent"]
            elif status == "paused":
                state_label = "Pausado"
                bar_col = t["paused"]
                state_col = t["text_muted"]
            elif status == "waiting":
                state_label = "En cola"
                bar_col = t["paused"]
                state_col = t["text_muted"]
            elif status == "complete":
                state_label = "Completado"
                bar_col = t["complete"]
                state_col = t["complete"]
            else:
                state_label = "Error"
                bar_col = t["danger"]
                state_col = t["danger"]

            if status == "complete":
                size_info = d["total_size_str"]
            elif d["is_metadata"]:
                size_info = "Descargando metadatos..."
            else:
                size_info = f"{d['completed_size_str']} / {d['total_size_str']} ({d['progress']:.0f}%)"

            meta_parts = [size_info]
            if status == "active" and not d["is_metadata"]:
                if d["speed"] > 0:
                    meta_parts.append(d["speed_str"])
                if d["eta"] and d["eta"] != "∞":
                    meta_parts.append(f"ETA {d['eta']}")
            meta_str = "  ·  ".join(meta_parts)

            async def on_toggle_pause(e, target_gid=gid):
                try:
                    await asyncio.get_running_loop().run_in_executor(None, lambda: toggle_pause_download(target_gid))
                    await refresh_downloads_data()
                except Exception as ex:
                    show_toast(f"Error: {ex}", is_error=True)

            def on_delete_click(e, target_d=d):
                async def confirm_del(ev):
                    page.pop_dialog()
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda: remove_download(target_d["gid"], delete_files=True)
                        )
                        show_toast(f"Eliminado: {target_d['name']}")
                        await refresh_downloads_data()
                    except Exception as ex:
                        show_toast(f"Error al eliminar: {ex}", is_error=True)

                def cancel_del(ev):
                    page.pop_dialog()

                dlg = ft.AlertDialog(
                    modal=True,
                    bgcolor=t["bg_card"],
                    shape=ft.RoundedRectangleBorder(radius=4),
                    title=ft.Text("Eliminar descarga", size=15, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                    content=ft.Text(
                        f"¿Querés eliminar '{target_d['name']}' y borrar sus archivos temporales?",
                        size=13,
                        color=t["text_secondary"],
                    ),
                    actions=[
                        ft.TextButton(content="Cancelar", style=btn_text_style(), on_click=cancel_del),
                        ft.FilledButton(
                            content="Eliminar",
                            style=btn_primary_style(t["danger"]),
                            on_click=confirm_del,
                        ),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(dlg)

            actions = []
            if status != "complete":
                is_paused = status in ("paused", "waiting")
                actions.append(
                    ft.IconButton(
                        icon=ft.Icons.PLAY_ARROW_ROUNDED if is_paused else ft.Icons.PAUSE_ROUNDED,
                        icon_color=t["text_primary"] if is_paused else t["text_secondary"],
                        icon_size=18,
                        tooltip="Reanudar" if is_paused else "Pausar",
                        on_click=on_toggle_pause,
                    )
                )
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.CLOSE_ROUNDED,
                    icon_color=t["text_muted"],
                    icon_size=18,
                    tooltip="Eliminar",
                    on_click=on_delete_click,
                )
            )

            return ft.Container(
                bgcolor=t["bg_card"],
                border=ft.Border.all(1, t["border"]),
                border_radius=4,
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            d["name"],
                                            size=13.5,
                                            weight=ft.FontWeight.W_500,
                                            color=t["text_primary"],
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        ft.Row(
                                            [
                                                ft.Text(state_label, size=12, color=state_col, weight=ft.FontWeight.W_500),
                                                ft.Text("·", size=12, color=t["text_muted"]),
                                                ft.Text(meta_str, size=12, color=t["text_secondary"]),
                                            ],
                                            spacing=6,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Row(actions, spacing=0),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.ProgressBar(
                            value=pct,
                            bar_height=4,
                            color=bar_col,
                            bgcolor=t["progress_bg"],
                            border_radius=1,
                        ),
                    ],
                    spacing=8,
                ),
            )

        async def refresh_downloads_data():
            t = T()
            try:
                raw = await asyncio.get_running_loop().run_in_executor(None, get_all_downloads)
            except Exception:
                raw = []

            by_gid = {d["gid"]: d for d in raw}
            state["order_gids"] = [g for g in state["order_gids"] if g in by_gid] + [
                d["gid"] for d in raw if d["gid"] not in state["order_gids"]
            ]
            ordered = [by_gid[g] for g in state["order_gids"]]
            state["downloads"] = ordered

            act_n = sum(1 for d in ordered if d["status"] == "active")
            pau_n = sum(1 for d in ordered if d["status"] in ("paused", "waiting"))
            cmp_n = sum(1 for d in ordered if d["status"] == "complete")
            dl_spd = sum(d["speed"] for d in ordered if d["status"] == "active")

            parts = [f"{act_n} activa(s)", f"{pau_n} en pausa", f"{cmp_n} completada(s)"]
            if dl_spd > 0:
                parts.append(f"↓ {format_speed(dl_spd)}")
            summary_str = "  ·  ".join(parts)
            subtitle_stats.value = summary_str
            subtitle_stats.color = t["text_secondary"]
            topbar_stats_text.value = f"{act_n} activa(s)  ·  {pau_n} en pausa  ·  ↓ {format_speed(dl_spd)}"

            if not ordered:
                downloads_list_col.controls = [
                    ft.Container(
                        alignment=ft.Alignment.CENTER,
                        padding=60,
                        content=ft.Column(
                            [
                                ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=34, color=t["text_muted"]),
                                ft.Text("No hay descargas en curso", size=14, weight=ft.FontWeight.W_500, color=t["text_secondary"]),
                                ft.Text(
                                    "Pegá un enlace magnet arriba o buscá contenido en la pestaña Buscar.",
                                    size=12.5,
                                    color=t["text_muted"],
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=6,
                        ),
                    )
                ]
            else:
                downloads_list_col.controls = [_build_download_card(d) for d in ordered]

            page.update()

        def sort_and_render_search():
            t = T()
            items = state["search_results"]
            mode = state["search_sort"]
            if mode == "seeders":
                items.sort(key=lambda x: (x["seeders"], x["size_bytes"]), reverse=True)
            elif mode == "size":
                items.sort(key=lambda x: x["size_bytes"], reverse=True)
            elif mode == "name":
                items.sort(key=lambda x: x["name"].lower())

            checked = state["search_checked"]
            download_selected_btn.visible = len(checked) > 0
            download_selected_btn.content = f"Descargar seleccionados ({len(checked)})"
            download_selected_btn.style = btn_primary_style()

            if not items:
                search_results_col.controls = []
                page.update()
                return

            cards = []
            for it in items:
                seeds = it["seeders"]
                dot_color = t["complete"] if seeds >= 10 else (t["accent"] if seeds >= 1 else t["text_muted"])
                is_chk = it["magnet"] in checked

                def on_chk_change(e, mag=it["magnet"]):
                    if e.control.value:
                        state["search_checked"].add(mag)
                    else:
                        state["search_checked"].discard(mag)
                    download_selected_btn.visible = len(state["search_checked"]) > 0
                    download_selected_btn.content = f"Descargar seleccionados ({len(state['search_checked'])})"
                    page.update()

                async def on_dl_single(e, item=it):
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, lambda: add_download(item["magnet"], state["config"]["download_path"], quiet=True)
                        )
                        show_toast(f"Descargando: {item['name']}")
                        await refresh_downloads_data()
                    except Exception as ex:
                        show_toast(f"Error: {ex}", is_error=True)

                cards.append(
                    ft.Container(
                        bgcolor=t["bg_card"],
                        border=ft.Border.all(1, t["accent"] if is_chk else t["border"]),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                        content=ft.Row(
                            [
                                ft.Checkbox(value=is_chk, on_change=on_chk_change, active_color=t["accent"]),
                                ft.Column(
                                    [
                                        ft.Text(
                                            it["name"],
                                            size=13,
                                            weight=ft.FontWeight.W_500,
                                            color=t["text_primary"],
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                        ),
                                        ft.Row(
                                            [
                                                ft.Container(width=7, height=7, border_radius=1, bgcolor=dot_color),
                                                ft.Text(
                                                    f"{it['size']}  ·  {seeds} seeds  ·  {it['uploaded']}",
                                                    size=12,
                                                    color=t["text_secondary"],
                                                ),
                                            ],
                                            spacing=6,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.OutlinedButton(
                                    content="Descargar",
                                    height=32,
                                    style=btn_outline_style(),
                                    on_click=on_dl_single,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=8,
                        ),
                    )
                )

            search_results_col.controls = cards
            page.update()

        async def on_search_submit(e=None):
            t = T()
            q = (search_input.value or "").strip()
            if not q or state["is_searching"]:
                return

            state["is_searching"] = True
            state["search_status"] = f"Buscando '{q}'..."
            search_status_text.value = state["search_status"]
            search_results_col.controls = [
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    padding=50,
                    content=ft.ProgressRing(color=t["accent"], width=26, height=26, stroke_width=2.5),
                )
            ]
            page.update()

            items, err = await asyncio.get_running_loop().run_in_executor(None, lambda: _search_torrents_sync(q))
            state["is_searching"] = False
            state["search_results"] = items
            state["search_checked"].clear()

            if err:
                state["search_status"] = err
                search_status_text.value = err
                search_results_col.controls = []
                page.update()
            else:
                state["search_status"] = f"{len(items)} resultados para '{q}'"
                search_status_text.value = state["search_status"]
                sort_and_render_search()

        search_input.on_submit = on_search_submit

        async def on_download_checked(e):
            checked = state["search_checked"]
            if not checked:
                return
            chosen = [it for it in state["search_results"] if it["magnet"] in checked]
            added = 0
            for item in chosen:
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda m=item["magnet"]: add_download(m, state["config"]["download_path"], quiet=True)
                    )
                    added += 1
                except Exception:
                    pass
            state["search_checked"].clear()
            sort_and_render_search()
            if added:
                show_toast(f"{added} descarga(s) agregada(s)")
                await refresh_downloads_data()

        download_selected_btn.on_click = on_download_checked

        async def refresh_library_view(e=None):
            t = T()
            lib_data = await asyncio.get_running_loop().run_in_executor(
                None, lambda: _scan_media_library(state["config"]["media_path"])
            )
            state["library"] = lib_data
            movies = lib_data["movies"]
            shows = lib_data["shows"]
            lib_summary_text.value = f"{len(movies)} película(s)  ·  {len(shows)} serie(s)"
            lib_summary_text.color = t["text_secondary"]

            if not movies:
                movies_list_col.controls = [
                    ft.Text("Sin películas organizadas.", size=13, color=t["text_muted"])
                ]
            else:
                movies_list_col.controls = [
                    ft.Container(
                        bgcolor=t["bg_card"],
                        border=ft.Border.all(1, t["border"]),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(m["title"], size=13, weight=ft.FontWeight.W_500, color=t["text_primary"]),
                                        ft.Text(f"{m['files_count']} archivo(s) · {m['size_str']}", size=12, color=t["text_secondary"]),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                                    icon_color=t["text_secondary"],
                                    icon_size=18,
                                    tooltip="Abrir carpeta",
                                    on_click=lambda e, p=m["path"]: _open_folder_in_os(p),
                                ),
                            ]
                        ),
                    )
                    for m in movies
                ]

            if not shows:
                shows_list_col.controls = [
                    ft.Text("Sin series organizadas.", size=13, color=t["text_muted"])
                ]
            else:
                shows_list_col.controls = [
                    ft.Container(
                        bgcolor=t["bg_card"],
                        border=ft.Border.all(1, t["border"]),
                        border_radius=4,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                        content=ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(s["title"], size=13, weight=ft.FontWeight.W_500, color=t["text_primary"]),
                                        ft.Text(
                                            f"{s['seasons_count']} temp. · {s['episodes_count']} ep. · {s['size_str']}",
                                            size=12,
                                            color=t["text_secondary"],
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                                    icon_color=t["text_secondary"],
                                    icon_size=18,
                                    tooltip="Abrir carpeta",
                                    on_click=lambda e, p=s["path"]: _open_folder_in_os(p),
                                ),
                            ]
                        ),
                    )
                    for s in shows
                ]

            page.update()

        async def pick_dl_dir(e):
            chosen = await file_picker.get_directory_path(dialog_title="Seleccionar carpeta de descargas")
            if chosen:
                dl_path_field.value = chosen
                page.update()

        async def pick_media_dir(e):
            chosen = await file_picker.get_directory_path(dialog_title="Seleccionar carpeta multimedia")
            if chosen:
                media_path_field.value = chosen
                page.update()

        def on_save_config(e):
            new_dl = (dl_path_field.value or "").strip()
            new_media = (media_path_field.value or "").strip()
            if not new_dl or not new_media:
                show_toast("Las rutas no pueden estar vacías", is_error=True)
                return
            try:
                Path(new_dl).mkdir(parents=True, exist_ok=True)
                Path(new_media).mkdir(parents=True, exist_ok=True)
                state["config"]["download_path"] = new_dl
                state["config"]["media_path"] = new_media
                state["config"]["theme_mode"] = state["theme_key"]
                _save_config_dict(state["config"])
                show_toast("Configuración guardada")
            except Exception as ex:
                show_toast(f"Error al guardar: {ex}", is_error=True)

        async def on_restart_daemon(e):
            state["daemon_msg"] = "Reiniciando motor aria2c..."
            daemon_status_badge.value = state["daemon_msg"]
            page.update()

            def _do_restart():
                _kill_aria2c()
                _start_daemon()
                return _daemon_running()

            ok = await asyncio.get_running_loop().run_in_executor(None, _do_restart)
            if ok:
                state["daemon_msg"] = "Motor aria2c activo en segundo plano"
                show_toast("Motor aria2c reiniciado")
            else:
                state["daemon_msg"] = "Motor aria2c desconectado"
                show_toast("No se pudo reiniciar aria2c", is_error=True)
            daemon_status_badge.value = state["daemon_msg"]
            page.update()

        async def on_create_shortcuts(e):
            paths = await asyncio.get_running_loop().run_in_executor(None, install_desktop_shortcut)
            if paths:
                show_toast("Acceso directo actualizado en el sistema")
            else:
                show_toast("No se pudo actualizar el acceso directo", is_error=True)

        def on_sort_select(e):
            state["search_sort"] = e.control.value or "seeders"
            sort_and_render_search()

        async def toggle_theme_mode(e=None):
            state["theme_key"] = "light" if state["theme_key"] == "dark" else "dark"
            state["config"]["theme_mode"] = state["theme_key"]
            try:
                _save_config_dict(state["config"])
            except Exception:
                pass
            await rebuild_layout()

        async def select_tab(idx: int):
            state["active_tab"] = idx
            await rebuild_layout()

        # ===================================================================
        # Full Layout Builder: Fixed Top Bar + Fixed Left Sidebar + Workspace
        # ===================================================================

        async def rebuild_layout():
            t = T()
            sh = SHELL_STYLE
            is_dark = state["theme_key"] == "dark"
            page.theme_mode = ft.ThemeMode.DARK if is_dark else ft.ThemeMode.LIGHT
            page.bgcolor = t["bg_app"]

            for fld in (magnet_input, search_input, dl_path_field, media_path_field):
                fld.bgcolor = t["bg_input"]
                fld.border_color = t["border"]
                fld.focused_border_color = t["accent"]
                fld.color = t["text_primary"]
                fld.hint_style = ft.TextStyle(color=t["text_muted"], size=13)
                fld.label_style = ft.TextStyle(color=t["text_secondary"], size=12)

            subtitle_stats.color = t["text_secondary"]
            search_status_text.color = t["text_muted"]
            lib_summary_text.color = t["text_secondary"]
            daemon_status_badge.color = t["text_secondary"]

            # 1. Views
            downloads_view = ft.Container(
                expand=True,
                bgcolor=t["bg_app"],
                padding=ft.Padding.symmetric(horizontal=26, vertical=20),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("Descargas", size=18, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                                        subtitle_stats,
                                    ],
                                    spacing=2,
                                ),
                                ft.Row(
                                    [
                                        ft.OutlinedButton(content="Pausar / Reanudar", height=32, style=btn_outline_style(), on_click=on_pause_resume_all),
                                        ft.OutlinedButton(content="Limpiar completadas", height=32, style=btn_outline_style(), on_click=on_clear_completed),
                                    ],
                                    spacing=6,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            [
                                magnet_input,
                                ft.FilledButton(
                                    content="Agregar",
                                    height=38,
                                    style=btn_primary_style(),
                                    on_click=on_add_magnet_click,
                                ),
                                ft.OutlinedButton(
                                    content="Archivo .torrent",
                                    height=38,
                                    style=btn_outline_style(),
                                    on_click=on_pick_torrent_file,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Divider(color=t["border"], height=4),
                        downloads_list_col,
                    ],
                    spacing=12,
                    expand=True,
                ),
            )

            sort_dropdown = ft.Dropdown(
                value=state["search_sort"],
                width=165,
                text_size=13,
                color=t["text_primary"],
                bgcolor=t["bg_input"],
                border_color=t["border"],
                border_radius=4,
                options=[
                    ft.DropdownOption(key="seeders", text="Orden: Seeders"),
                    ft.DropdownOption(key="size", text="Orden: Tamaño"),
                    ft.DropdownOption(key="name", text="Orden: Nombre"),
                ],
                on_select=on_sort_select,
            )

            search_view = ft.Container(
                expand=True,
                bgcolor=t["bg_app"],
                padding=ft.Padding.symmetric(horizontal=26, vertical=20),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("Buscar", size=18, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                                        search_status_text,
                                    ],
                                    spacing=2,
                                ),
                                download_selected_btn,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            [
                                search_input,
                                ft.FilledButton(
                                    content="Buscar",
                                    height=38,
                                    style=btn_primary_style(),
                                    on_click=on_search_submit,
                                ),
                                sort_dropdown,
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(color=t["border"], height=4),
                        search_results_col,
                    ],
                    spacing=12,
                    expand=True,
                ),
            )

            library_view = ft.Container(
                expand=True,
                bgcolor=t["bg_app"],
                padding=ft.Padding.symmetric(horizontal=26, vertical=20),
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text("Biblioteca", size=18, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                                        lib_summary_text,
                                    ],
                                    spacing=2,
                                ),
                                ft.Row(
                                    [
                                        ft.OutlinedButton(
                                            content="Abrir carpeta Media",
                                            height=34,
                                            style=btn_outline_style(),
                                            on_click=lambda e: _open_folder_in_os(state["config"]["media_path"]),
                                        ),
                                        ft.FilledButton(
                                            content="Organizar ahora",
                                            height=34,
                                            style=btn_primary_style(),
                                            on_click=on_organize_now,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Divider(color=t["border"], height=4),
                        ft.Row(
                            [
                                ft.Container(
                                    expand=True,
                                    content=ft.Column(
                                        [
                                            ft.Text("Películas", size=13.5, weight=ft.FontWeight.W_600, color=t["text_secondary"]),
                                            movies_list_col,
                                        ],
                                        spacing=8,
                                        expand=True,
                                    ),
                                ),
                                ft.VerticalDivider(width=20, color=t["border"]),
                                ft.Container(
                                    expand=True,
                                    content=ft.Column(
                                        [
                                            ft.Text("Series", size=13.5, weight=ft.FontWeight.W_600, color=t["text_secondary"]),
                                            shows_list_col,
                                        ],
                                        spacing=8,
                                        expand=True,
                                    ),
                                ),
                            ],
                            expand=True,
                        ),
                    ],
                    spacing=12,
                    expand=True,
                ),
            )

            settings_view = ft.Container(
                expand=True,
                bgcolor=t["bg_app"],
                padding=ft.Padding.symmetric(horizontal=26, vertical=20),
                content=ft.Column(
                    [
                        ft.Text("Ajustes", size=18, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                        ft.Divider(color=t["border"], height=4),
                        ft.Container(
                            bgcolor=t["bg_card"],
                            border=ft.Border.all(1, t["border"]),
                            border_radius=4,
                            padding=18,
                            content=ft.Column(
                                [
                                    ft.Text("Carpetas", size=14, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                                    ft.Row(
                                        [
                                            dl_path_field,
                                            ft.OutlinedButton(content="Cambiar", height=38, style=btn_outline_style(), on_click=pick_dl_dir),
                                        ],
                                        spacing=8,
                                    ),
                                    ft.Row(
                                        [
                                            media_path_field,
                                            ft.OutlinedButton(content="Cambiar", height=38, style=btn_outline_style(), on_click=pick_media_dir),
                                        ],
                                        spacing=8,
                                    ),
                                    ft.Row(
                                        [
                                            ft.FilledButton(
                                                content="Guardar cambios",
                                                height=36,
                                                style=btn_primary_style(),
                                                on_click=on_save_config,
                                            )
                                        ],
                                        alignment=ft.MainAxisAlignment.END,
                                    ),
                                ],
                                spacing=12,
                            ),
                        ),
                        ft.Container(
                            bgcolor=t["bg_card"],
                            border=ft.Border.all(1, t["border"]),
                            border_radius=4,
                            padding=18,
                            content=ft.Column(
                                [
                                    ft.Text("Apariencia y sistema", size=14, weight=ft.FontWeight.W_600, color=t["text_primary"]),
                                    daemon_status_badge,
                                    ft.Row(
                                        [
                                            ft.OutlinedButton(
                                                content="Cambiar a Modo Claro" if is_dark else "Cambiar a Modo Oscuro",
                                                height=34,
                                                style=btn_outline_style(),
                                                on_click=toggle_theme_mode,
                                            ),
                                            ft.OutlinedButton(
                                                content="Reiniciar aria2c",
                                                height=34,
                                                style=btn_outline_style(),
                                                on_click=on_restart_daemon,
                                            ),
                                            ft.OutlinedButton(
                                                content="Actualizar acceso directo",
                                                height=34,
                                                style=btn_outline_style(),
                                                on_click=on_create_shortcuts,
                                            ),
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                ],
                                spacing=10,
                            ),
                        ),
                    ],
                    spacing=14,
                    expand=True,
                ),
            )

            views = [downloads_view, search_view, library_view, settings_view]

            # 2. Top Header Bar (fixed neutral dark-steel color across Dark & Light mode)
            topbar = ft.Container(
                height=48,
                bgcolor=sh["topbar_bg"],
                padding=ft.Padding.symmetric(horizontal=18),
                border=ft.Border.only(bottom=ft.BorderSide(1, sh["border"])),
                content=ft.Row(
                    [
                        ft.Row(
                            [
                                ft.Icon(ft.Icons. DOCK_ROUNDED, size=18, color=sh["accent"]),
                                ft.Text(
                                    "Media Manager",
                                    size=14,
                                    weight=ft.FontWeight.W_600,
                                    color=sh["text_primary"],
                                ),
                                ft.Container(
                                    width=1,
                                    height=16,
                                    bgcolor=sh["border"],
                                    margin=ft.Padding.symmetric(horizontal=6),
                                ),
                                ft.Container(
                                    bgcolor=sh["pill_bg"],
                                    border=ft.Border.all(1, sh["border"]),
                                    border_radius=3,
                                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                    content=topbar_stats_text,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            [
                                ft.OutlinedButton(
                                    content="Organizar",
                                    height=30,
                                    style=btn_topbar_style(),
                                    on_click=on_organize_now,
                                ),
                                ft.OutlinedButton(
                                    content="Modo claro" if is_dark else "Modo oscuro",
                                    icon=ft.Icons.LIGHT_MODE_OUTLINED if is_dark else ft.Icons.DARK_MODE_OUTLINED,
                                    height=30,
                                    style=btn_topbar_style(),
                                    on_click=toggle_theme_mode,
                                ),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )

            # 3. Left Sidebar (fixed neutral steel-slate color across Dark & Light mode)
            nav_defs = [
                (0, "Descargas", ft.Icons.DOWNLOAD_OUTLINED, ft.Icons.DOWNLOAD_ROUNDED),
                (1, "Buscar", ft.Icons.SEARCH_OUTLINED, ft.Icons.SEARCH_ROUNDED),
                (2, "Biblioteca", ft.Icons.FOLDER_OUTLINED, ft.Icons.FOLDER_ROUNDED),
                (3, "Ajustes", ft.Icons.TUNE_OUTLINED, ft.Icons.TUNE_ROUNDED),
            ]

            nav_buttons = []
            for idx, label, ic_off, ic_on in nav_defs:
                is_sel = state["active_tab"] == idx

                async def on_nav_tap(e, target_idx=idx):
                    await select_tab(target_idx)

                nav_buttons.append(
                    ft.Container(
                        bgcolor=sh["item_active_bg"] if is_sel else None,
                        border=ft.Border.only(
                            left=ft.BorderSide(3, sh["item_active_bar"] if is_sel else "transparent")
                        ),
                        border_radius=3,
                        padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                        ink=True,
                        on_click=on_nav_tap,
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ic_on if is_sel else ic_off,
                                    size=17,
                                    color=sh["text_primary"] if is_sel else sh["text_secondary"],
                                ),
                                ft.Text(
                                    label,
                                    size=13,
                                    weight=ft.FontWeight.W_600 if is_sel else ft.FontWeight.W_400,
                                    color=sh["text_primary"] if is_sel else sh["text_secondary"],
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            sidebar = ft.Container(
                width=180,
                bgcolor=sh["sidebar_bg"],
                padding=ft.Padding.symmetric(horizontal=10, vertical=12),
                content=ft.Column(
                    nav_buttons,
                    spacing=3,
                    expand=True,
                ),
            )

            root_container.content = ft.Column(
                [
                    topbar,
                    ft.Row(
                        [
                            sidebar,
                            ft.VerticalDivider(width=1, color=sh["border"]),
                            views[state["active_tab"]],
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=0,
                expand=True,
            )

            if state["active_tab"] == 0:
                await refresh_downloads_data()
            elif state["active_tab"] == 1:
                sort_and_render_search()
            elif state["active_tab"] == 2:
                await refresh_library_view()
            else:
                page.update()

        page.add(root_container)

        if initial_uri:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: add_download(initial_uri, state["config"]["download_path"], quiet=True)
                )
            except Exception:
                pass

        await rebuild_layout()

        async def poll_downloads_loop():
            while state["running"]:
                if state["active_tab"] == 0:
                    await refresh_downloads_data()
                await asyncio.sleep(1.0)

        page.run_task(poll_downloads_loop)

    ft.run(main)


def main():
    uri_arg = sys.argv[1] if len(sys.argv) > 1 else None
    launch_gui(initial_uri=uri_arg)


if __name__ == "__main__":
    main()
