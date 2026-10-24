import subprocess
import json
import os
import shutil
import sys
import time
from pathlib import Path
import questionary
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from .config import get_base_dir, get_public_dir, load_config


def _ensure_utf8_console():
    """Ensure Windows console and Python stdio streams use UTF-8 encoding."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_ensure_utf8_console()
console = Console()


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


def get_binary_path(name: str) -> str:
    """Find binary in the same environment/directory as sys.executable, venv, or fallback to PATH."""
    exec_dir = Path(sys.executable).parent
    
    # Check next to python executable (e.g. venv/bin or venv/Scripts)
    found = shutil.which(name, path=str(exec_dir))
    if found:
        return found
        
    # Check Scripts directory if running under main Python install
    scripts_dir = exec_dir / "Scripts"
    if scripts_dir.exists():
        found = shutil.which(name, path=str(scripts_dir))
        if found:
            return found
            
    # Check standard media_manager venvs (active base_dir, Public, and user home)
    for base in (get_base_dir(), get_public_dir(), Path.home()):
        venv_dir = base / ".local" / "share" / "media_manager" / "venv"
        for sub in ["Scripts", "bin"]:
            candidate = venv_dir / sub
            if candidate.exists():
                found = shutil.which(name, path=str(candidate))
                if found:
                    return found
        local_bin = base / ".local" / "bin"
        if local_bin.exists():
            found = shutil.which(name, path=str(local_bin))
            if found:
                return found

    if os.name == "nt":
        _refresh_windows_path()

    found = shutil.which(name)
    if found:
        return found
    return name


def get_pirate_command() -> list:
    """Return command list for pirate-get.
    Prefers executing through the active Python interpreter [sys.executable, "-m", "pirate.pirate"]
    to bypass Windows App Control / WDAC restrictions that block unsigned launcher .exe stubs.
    """
    try:
        import pirate.pirate
        return [sys.executable, "-m", "pirate.pirate"]
    except ImportError:
        pass
    return [get_binary_path("pirate-get")]


def search_interactive(query_str: str) -> str:
    """Runs pirate-get in JSON mode, displays a rich table, and returns the chosen magnet link."""
    pirate_cmd = get_pirate_command()
    with console.status(f"[bold green]Searching for '{query_str}'..."):
        try:
            # -j for JSON output. We don't use -C here because we'll handle the output manually
            result = subprocess.run(
                [*pirate_cmd, query_str, "-j"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True
            )
        except subprocess.CalledProcessError:
            console.print("[bold red]Search failed or no results found.[/]")
            return None
        except (FileNotFoundError, OSError) as e:
            console.print(f"[bold red]Error running search provider:[/] {e}")
            return None

    if not result.stdout or not result.stdout.strip():
        console.print("[bold yellow]No torrents found for your query.[/]")
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        console.print("[bold red]Failed to parse search results.[/]")
        return None

    if not data:
        console.print("[bold yellow]No torrents found for your query.[/]")
        return None

    # Print a beautiful table of results
    table = Table(title=f"Search Results for '{query_str}'", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Name", style="green")
    table.add_column("Size", justify="right", style="cyan")
    table.add_column("Seeders", justify="right", style="bold green")
    table.add_column("Leechers", justify="right", style="red")

    choices = []
    
    # pirate-get json output is usually a list of dicts.
    for i, item in enumerate(data):
        idx_str = str(i + 1)
        name = item.get("name", "Unknown")
        size = item.get("size", "Unknown")
        seeders = str(item.get("seeders", 0))
        leechers = str(item.get("leechers", 0))
        magnet = item.get("magnet")
        
        # Don't add items without magnet links
        if not magnet:
            continue

        table.add_row(idx_str, name, size, seeders, leechers)
        
        # Add to interactive choices
        choices.append(
            questionary.Choice(
                title=f"{name} ({size}) [S: {seeders}, L: {leechers}]",
                value=magnet
            )
        )

    console.print(table)
    
    # Prompt the user to select one
    if not choices:
        console.print("[bold red]No valid torrents with magnet links found.[/]")
        return None
        
    choices.append(questionary.Choice(title="❌ Cancel", value="__cancel__"))

    selected_magnet = questionary.select(
        "Select a torrent to download:",
        choices=choices,
        style=questionary.Style([
            ('qmark', 'fg:#ff9d00 bold'),
            ('question', 'bold'),
            ('answer', 'fg:#ff9d00 bold'),
            ('pointer', 'fg:#ff9d00 bold'),
            ('highlighted', 'fg:#ff9d00 bold'),
            ('selected', 'fg:#cc5454'),
            ('separator', 'fg:#cc5454'),
            ('instruction', ''),
            ('text', ''),
            ('disabled', 'fg:#858585 italic')
        ]),
        use_indicator=True
    ).ask()

    if not selected_magnet or selected_magnet == "__cancel__":
        return None

    return selected_magnet


def _render_progress_bar(progress: float, status: str, bar_width: int = 12) -> str:
    """Render a colored block progress bar and percentage."""
    pct = max(0.0, min(100.0, float(progress)))
    filled = int(round((pct / 100.0) * bar_width))
    filled = max(0, min(bar_width, filled))
    empty = bar_width - filled

    if status == "complete":
        color = "bright_green"
    elif status == "active":
        color = "green" if pct > 0 else "cyan"
    elif status == "paused":
        color = "yellow"
    elif status == "waiting":
        color = "blue"
    elif status == "error":
        color = "red"
    else:
        color = "white"

    bar_str = f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/]"
    return f"{bar_str} [bold {color}]{pct:5.1f}%[/]"


def _render_status_badge(d: dict, compact: bool = False) -> str:
    """Render a clear status indicator showing whether the download is active, inactive/paused, or completed."""
    status = d.get("status", "active")
    is_meta = d.get("is_metadata", False)

    if status == "active":
        if is_meta:
            return "[bold cyan]● Meta[/]" if compact else "[bold cyan]● Activo (Meta)[/]"
        return "[bold green]● Activo[/]"
    elif status == "paused":
        return "[bold yellow]⏸ Pausado[/]" if compact else "[bold yellow]⏸ Inactivo (Pausa)[/]"
    elif status == "waiting":
        return "[bold blue]⏳ En cola[/]" if compact else "[bold blue]⏳ Inactivo (Cola)[/]"
    elif status == "complete":
        return "[bold bright_green]✔ Completo[/]" if compact else "[bold bright_green]✔ Completado[/]"
    elif status == "error":
        return "[bold red]✖ Error[/]" if compact else "[bold red]✖ Inactivo (Error)[/]"
    elif status == "removed":
        return "[dim]🗑 Eliminado[/]"
    return f"[white]{status}[/]"


def build_downloads_view(
    downloads: list,
    selected_idx: int = 0,
    confirm_delete_item: dict = None,
    feedback_msg: str = "",
    interactive: bool = True,
    term_width: int = 120,
):
    """Build the Rich renderable dashboard for the download manager."""
    from .downloader import format_speed

    active_count = sum(1 for d in downloads if d["status"] == "active")
    inactive_count = sum(1 for d in downloads if d["status"] in ("paused", "waiting"))
    complete_count = sum(1 for d in downloads if d["status"] == "complete")
    error_count = sum(1 for d in downloads if d["status"] == "error")

    total_dl_speed = sum(d["speed"] for d in downloads if d["status"] == "active")
    total_ul_speed = sum(d["upload_speed"] for d in downloads if d["status"] == "active")

    # 1. Header summary panel
    summary_parts = [
        f"[bold green]● Activas: {active_count}[/]",
        f"[bold yellow]⏸ Inactivas/Pausadas: {inactive_count}[/]",
        f"[bold bright_green]✔ Completadas: {complete_count}[/]",
    ]
    if error_count > 0:
        summary_parts.append(f"[bold red]✖ Errores: {error_count}[/]")
    summary_parts.append(f"[bold cyan]⬇ {format_speed(total_dl_speed)}[/]")
    summary_parts.append(f"[dim]⬆ {format_speed(total_ul_speed)}[/]")

    header_text = "   │   ".join(summary_parts)
    header_panel = Panel(
        header_text,
        title="[bold magenta]🎬 Media Manager — Visor de Descargas[/]",
        border_style="magenta",
        padding=(0, 1),
    )

    # 2. Main Downloads Table with responsive column sizing
    compact = term_width < 95
    bar_width = 10 if term_width >= 115 else (8 if term_width >= 95 else 5)
    show_peers = term_width >= 130
    show_eta = term_width >= 100

    idx_w = 3
    status_w = 10 if compact else 18
    prog_w = bar_width + 7
    size_w = 15 if compact else 17
    speed_w = 10 if compact else 12
    peers_w = 9 if show_peers else 0
    eta_w = 7 if show_eta else 0

    num_cols = 6 + (1 if show_peers else 0) + (1 if show_eta else 0)
    # Borders (num_cols + 1) + horizontal padding (2 * num_cols when pad_edge=False -> 2*(num_cols-1) + 2)
    chrome_w = (num_cols * 3) + 1
    fixed_w = idx_w + status_w + prog_w + size_w + speed_w + peers_w + eta_w + chrome_w
    name_w = max(14, term_width - fixed_w)

    table = Table(
        box=box.ROUNDED,
        expand=True,
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        pad_edge=False,
        padding=(0, 1),
    )

    table.add_column("#", width=idx_w, justify="left", no_wrap=True)
    table.add_column("Nombre", ratio=1, min_width=name_w, max_width=name_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Estado", width=status_w, justify="left", no_wrap=True)
    table.add_column("Progreso", width=prog_w, justify="right", no_wrap=True)
    table.add_column("Tamaño", width=size_w, justify="right", no_wrap=True)
    table.add_column("Velocidad", width=speed_w, justify="right", no_wrap=True)
    if show_peers:
        table.add_column("Peers", width=peers_w, justify="center", no_wrap=True)
    if show_eta:
        table.add_column("ETA", width=eta_w, justify="right", no_wrap=True)

    if not downloads:
        empty_row = ["-", "[dim italic]No hay descargas en la lista[/]", "[dim]-[/]", "[dim]-[/]", "[dim]-[/]", "[dim]-[/]"]
        if show_peers:
            empty_row.append("[dim]-[/]")
        if show_eta:
            empty_row.append("[dim]-[/]")
        table.add_row(*empty_row)
    else:
        for i, d in enumerate(downloads):
            is_sel = interactive and (i == selected_idx)
            status = d["status"]

            idx_cell = f"[bold bright_yellow]▶ {i + 1}[/]" if is_sel else f"[dim]  {i + 1}[/]"

            if is_sel:
                name_cell = f"[bold bright_white]{d['name']}[/]"
            elif status == "complete":
                name_cell = f"[bright_green]{d['name']}[/]"
            elif status == "paused":
                name_cell = f"[yellow]{d['name']}[/]"
            elif status == "error":
                name_cell = f"[red]{d['name']}[/]"
            else:
                name_cell = f"[white]{d['name']}[/]"

            status_cell = _render_status_badge(d, compact=compact)
            progress_cell = _render_progress_bar(d["progress"], status, bar_width=bar_width)

            if status == "complete":
                size_cell = f"[bright_green]{d['total_size_str'] if compact else d['size_str']}[/]"
            elif d["is_metadata"]:
                size_cell = "[cyan]Metadatos...[/]"
            else:
                size_cell = f"[cyan]{d['completed_size_str']}[/] [dim]/[/] [bold cyan]{d['total_size_str']}[/]"

            if status == "active":
                speed_cell = f"[bold cyan]↓ {d['speed_str']}[/]" if d["speed"] > 0 else "[dim]0 B/s[/]"
            else:
                speed_cell = "[dim]-[/]"

            row_cells = [idx_cell, name_cell, status_cell, progress_cell, size_cell, speed_cell]

            if show_peers:
                if status == "active":
                    peers_cell = f"[green]S:{d['seeders']}[/] [dim]P:{d['connections']}[/]"
                else:
                    peers_cell = "[dim]-[/]"
                row_cells.append(peers_cell)

            if show_eta:
                if status == "active":
                    eta_cell = f"[magenta]{d['eta']}[/]"
                elif status == "complete":
                    eta_cell = "[bright_green]Listo[/]"
                elif status == "paused":
                    eta_cell = "[yellow]Pausado[/]"
                elif status == "waiting":
                    eta_cell = "[blue]En cola[/]"
                else:
                    eta_cell = "[dim]-[/]"
                row_cells.append(eta_cell)

            row_style = "on #1e293b" if is_sel else None
            table.add_row(*row_cells, style=row_style)

    if not interactive:
        return Group(header_panel, table)

    # 3. Footer / Inspector & Controls Panel
    footer_lines = []

    if downloads and 0 <= selected_idx < len(downloads):
        sel = downloads[selected_idx]
        state_word = "ACTIVO" if sel["status"] == "active" else (
            "COMPLETADO" if sel["status"] == "complete" else f"INACTIVO ({sel['status'].upper()})"
        )
        footer_lines.append(
            f"📌 [bold bright_white]{sel['name']}[/]  [dim](GID: {sel['gid']})[/]  •  "
            f"Estado: [bold]{state_word}[/]  •  "
            f"Tamaño: [cyan]{sel['completed_size_str']}[/] / [bold cyan]{sel['total_size_str']}[/] ({sel['progress']:.1f}%)  •  "
            f"Peers: S:{sel['seeders']} P:{sel['connections']}"
        )
        if sel.get("error_message"):
            footer_lines.append(f"   [bold red]⚠ Error: {sel['error_message']}[/]")
    else:
        footer_lines.append("[dim]💡 Tip: Usá 'media-manager search <nombre>' o 'media-manager download <magnet>' para agregar descargas.[/]")

    if confirm_delete_item is not None:
        footer_lines.append(
            f"\n[bold yellow]⚠️  ¿Seguro que querés eliminar [/][bold bright_white]'{confirm_delete_item['name']}'[/][bold yellow]?[/]   "
            f"[bold bright_green][S / Y / Enter] Sí, eliminar[/]   [bold bright_red][N / Esc] Cancelar[/]"
        )
    elif feedback_msg:
        footer_lines.append(f"\n{feedback_msg}")

    controls_line = (
        "[bold cyan][↑/↓][/] Seleccionar   "
        "[bold yellow][P / Espacio][/] Pausar/Reanudar   "
        "[bold red][D / Supr][/] Eliminar   "
        "[bold bright_green][C][/] Clear Completados   "
        "[bold magenta][A][/] Pausar/Reanudar Todo   "
        "[bold blue][O][/] Organizar   "
        "[bold white][Q / Esc][/] Salir"
    )
    footer_lines.append("\n" + controls_line)

    footer_panel = Panel(
        "\n".join(footer_lines),
        border_style="yellow" if confirm_delete_item else "cyan",
        padding=(0, 1),
    )

    return Group(header_panel, table, footer_panel)


def _read_key_windows(timeout: float = 0.1):
    """Non-blocking single keypress reader for Windows consoles."""
    import msvcrt
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                ch2 = msvcrt.getwch()
                mapping = {
                    "H": "UP",
                    "P": "DOWN",
                    "S": "DELETE",
                    "G": "HOME",
                    "O": "END",
                    "I": "PGUP",
                    "Q": "PGDN",
                }
                return mapping.get(ch2, "")
            if ch == "\x1b":
                time.sleep(0.01)
                if msvcrt.kbhit():
                    seq = ""
                    while msvcrt.kbhit():
                        seq += msvcrt.getwch()
                    if seq in ("[A", "OA"):
                        return "UP"
                    if seq in ("[B", "OB"):
                        return "DOWN"
                    if seq == "[3~":
                        return "DELETE"
                    if seq in ("[H", "[1~"):
                        return "HOME"
                    if seq in ("[F", "[4~"):
                        return "END"
                    return ""
                return "ESC"
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch == " ":
                return "SPACE"
            if ch == "\x08":
                return "DELETE"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch.lower()
        time.sleep(0.015)
    return None


def _read_key_posix(timeout: float = 0.1):
    """Non-blocking single keypress reader for POSIX terminals."""
    import select
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    if not rlist:
        return None
    ch = sys.stdin.read(1)
    if not ch:
        return None
    if ch == "\x1b":
        r2, _, _ = select.select([sys.stdin], [], [], 0.02)
        if r2:
            seq = sys.stdin.read(1)
            if seq in ("[", "O"):
                r3, _, _ = select.select([sys.stdin], [], [], 0.02)
                if r3:
                    code = sys.stdin.read(1)
                    if code == "A":
                        return "UP"
                    if code == "B":
                        return "DOWN"
                    if code == "H":
                        return "HOME"
                    if code == "F":
                        return "END"
                    if code == "3":
                        r4, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if r4:
                            sys.stdin.read(1)
                        return "DELETE"
            return ""
        return "ESC"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch == " ":
        return "SPACE"
    if ch in ("\x7f", "\x08"):
        return "DELETE"
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch.lower()


def show_downloads_tui():
    """
    Launch the custom interactive Download Manager TUI.
    Supports live progress, size, active/inactive status, pausing/resuming individual
    downloads, deleting individual downloads, and clearing completed downloads.
    """
    from .downloader import (
        get_all_downloads,
        toggle_pause_download,
        remove_download,
        clear_completed_downloads,
        pause_all_downloads,
        resume_all_downloads,
    )
    from .organizer import organize_downloads

    # If not running in an interactive terminal, print a snapshot table and return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        downloads = get_all_downloads()
        console.print(build_downloads_view(downloads, interactive=False, term_width=console.size.width))
        return

    order_gids = []
    selected_idx = 0
    selected_gid = None
    confirm_delete_item = None
    feedback_msg = ""
    feedback_until = 0.0

    def set_feedback(msg: str, duration: float = 4.0):
        nonlocal feedback_msg, feedback_until
        feedback_msg = msg
        feedback_until = time.monotonic() + duration

    def fetch_ordered_downloads():
        nonlocal order_gids, selected_idx, selected_gid, confirm_delete_item
        raw = get_all_downloads()
        by_gid = {d["gid"]: d for d in raw}
        order_gids = [g for g in order_gids if g in by_gid] + [
            d["gid"] for d in raw if d["gid"] not in order_gids
        ]
        ordered = [by_gid[g] for g in order_gids]

        if not ordered:
            selected_idx = 0
            selected_gid = None
            confirm_delete_item = None
        else:
            if selected_gid and selected_gid in order_gids:
                selected_idx = order_gids.index(selected_gid)
            else:
                selected_idx = max(0, min(selected_idx, len(ordered) - 1))
                selected_gid = ordered[selected_idx]["gid"]

            if confirm_delete_item and confirm_delete_item["gid"] not in by_gid:
                confirm_delete_item = None

        return ordered

    old_posix_settings = None
    if os.name != "nt":
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old_posix_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            old_posix_settings = None

    read_key_fn = _read_key_windows if os.name == "nt" else _read_key_posix

    try:
        downloads = fetch_ordered_downloads()
        last_fetch = time.monotonic()

        with Live(
            build_downloads_view(
                downloads,
                selected_idx=selected_idx,
                confirm_delete_item=confirm_delete_item,
                feedback_msg=feedback_msg,
                interactive=True,
                term_width=console.size.width,
            ),
            console=console,
            auto_refresh=False,
            screen=True,
        ) as live:
            while True:
                now = time.monotonic()
                if feedback_msg and now >= feedback_until:
                    feedback_msg = ""

                if now - last_fetch >= 0.5:
                    downloads = fetch_ordered_downloads()
                    last_fetch = time.monotonic()

                live.update(
                    build_downloads_view(
                        downloads,
                        selected_idx=selected_idx,
                        confirm_delete_item=confirm_delete_item,
                        feedback_msg=feedback_msg,
                        interactive=True,
                        term_width=console.size.width,
                    ),
                    refresh=True,
                )

                key = read_key_fn(timeout=0.1)
                if not key:
                    continue

                # Handle delete confirmation modal state
                if confirm_delete_item is not None:
                    if key in ("y", "s", "ENTER"):
                        target = confirm_delete_item
                        confirm_delete_item = None
                        try:
                            remove_download(target["gid"], delete_files=True)
                            set_feedback(f"[bold green]🗑 Descarga eliminada:[/] [white]{target['name']}[/]")
                        except Exception as e:
                            set_feedback(f"[bold red]✖ Error al eliminar:[/] {e}")
                        downloads = fetch_ordered_downloads()
                        last_fetch = time.monotonic()
                    elif key in ("n", "ESC", "q"):
                        confirm_delete_item = None
                        set_feedback("[dim]Eliminación cancelada.[/]", duration=2.0)
                    continue

                # Normal navigation & action shortcuts
                if key in ("q", "ESC"):
                    break

                elif key in ("UP", "k", "w"):
                    if downloads:
                        selected_idx = (selected_idx - 1) % len(downloads)
                        selected_gid = downloads[selected_idx]["gid"]

                elif key in ("DOWN", "j", "s"):
                    if downloads:
                        selected_idx = (selected_idx + 1) % len(downloads)
                        selected_gid = downloads[selected_idx]["gid"]

                elif key == "HOME":
                    if downloads:
                        selected_idx = 0
                        selected_gid = downloads[0]["gid"]

                elif key == "END":
                    if downloads:
                        selected_idx = len(downloads) - 1
                        selected_gid = downloads[selected_idx]["gid"]

                elif key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                    idx_num = int(key) - 1
                    if 0 <= idx_num < len(downloads):
                        selected_idx = idx_num
                        selected_gid = downloads[selected_idx]["gid"]

                elif key in ("p", "SPACE"):
                    if not downloads:
                        set_feedback("[yellow]No hay descargas para pausar/reanudar.[/]")
                        continue
                    sel = downloads[selected_idx]
                    if sel["status"] == "complete":
                        set_feedback("[cyan]ℹ La descarga seleccionada ya está completada.[/]")
                        continue
                    try:
                        new_state = toggle_pause_download(sel["gid"])
                        if new_state == "paused":
                            set_feedback(f"[bold yellow]⏸ Descarga en pausa:[/] [white]{sel['name']}[/]")
                        elif new_state == "active":
                            set_feedback(f"[bold green]▶ Descarga reanudada:[/] [white]{sel['name']}[/]")
                        else:
                            set_feedback(f"[cyan]Estado actual:[/] {new_state}")
                    except Exception as e:
                        set_feedback(f"[bold red]✖ No se pudo cambiar el estado:[/] {e}")
                    downloads = fetch_ordered_downloads()
                    last_fetch = time.monotonic()

                elif key in ("d", "x", "DELETE"):
                    if not downloads:
                        set_feedback("[yellow]No hay descargas para eliminar.[/]")
                        continue
                    confirm_delete_item = downloads[selected_idx]

                elif key == "c":
                    completed_items = [d for d in downloads if d["status"] == "complete"]
                    if not completed_items:
                        set_feedback("[yellow]ℹ No hay descargas completadas para limpiar.[/]")
                        continue
                    try:
                        count = clear_completed_downloads()
                        cleared_n = max(count, len(completed_items))
                        set_feedback(f"[bold bright_green]✨ Se limpiaron {cleared_n} descarga(s) completada(s).[/]")
                    except Exception as e:
                        set_feedback(f"[bold red]✖ Error al limpiar completados:[/] {e}")
                    downloads = fetch_ordered_downloads()
                    last_fetch = time.monotonic()

                elif key == "a":
                    if not downloads:
                        continue
                    has_active = any(d["status"] in ("active", "waiting") for d in downloads)
                    has_paused = any(d["status"] == "paused" for d in downloads)
                    try:
                        if has_active:
                            pause_all_downloads()
                            set_feedback("[bold yellow]⏸ Todas las descargas activas fueron pausadas.[/]")
                        elif has_paused:
                            resume_all_downloads()
                            set_feedback("[bold green]▶ Todas las descargas en pausa fueron reanudadas.[/]")
                        else:
                            set_feedback("[cyan]ℹ No hay descargas activas ni en pausa.[/]")
                    except Exception as e:
                        set_feedback(f"[bold red]✖ Error:[/] {e}")
                    downloads = fetch_ordered_downloads()
                    last_fetch = time.monotonic()

                elif key == "o":
                    try:
                        cfg = load_config()
                        organize_downloads(cfg["download_path"], cfg["media_path"])
                        set_feedback("[bold bright_green]📁 Carpeta de descargas organizada correctamente.[/]")
                    except Exception as e:
                        set_feedback(f"[bold red]✖ Error al organizar:[/] {e}")
                    downloads = fetch_ordered_downloads()
                    last_fetch = time.monotonic()

    except KeyboardInterrupt:
        pass
    finally:
        if old_posix_settings is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_posix_settings)
            except Exception:
                pass
