import subprocess
import json
import os
import re
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


# ---------------------------------------------------------------------------
# Shared Keyboard Input Helpers (Navigation & Text Input)
# ---------------------------------------------------------------------------

def _get_clipboard_text() -> str:
    """Read text from the system clipboard if available."""
    try:
        import pyperclip
        return (pyperclip.paste() or "").replace("\r", "").replace("\n", " ").strip()
    except Exception:
        return ""


def _read_key_windows(timeout: float = 0.1, raw_case: bool = False):
    """Non-blocking keypress reader for Windows consoles."""
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
                    "K": "LEFT",
                    "M": "RIGHT",
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
                    if seq == "[5~":
                        return "PGUP"
                    if seq == "[6~":
                        return "PGDN"
                    return ""
                return "ESC"
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch == "\x08":
                return "BACKSPACE"
            if ch == "\x16":  # Ctrl+V
                return "PASTE"
            if ch == "\x15":  # Ctrl+U
                return "CLEAR_INPUT"
            if ch == "\x03":
                raise KeyboardInterrupt
            if raw_case:
                # Drain any immediately buffered printable characters (e.g. terminal paste)
                buf = ch
                while msvcrt.kbhit():
                    nxt = msvcrt.getwch()
                    if nxt in ("\r", "\n", "\x1b", "\x00", "\xe0", "\x08", "\x03"):
                        break
                    buf += nxt
                return buf
            if ch == " ":
                return "SPACE"
            return ch.lower()
        time.sleep(0.015)
    return None


def _read_key_posix(timeout: float = 0.1, raw_case: bool = False):
    """Non-blocking keypress reader for POSIX terminals."""
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
                    if code in ("3", "5", "6"):
                        r4, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if r4:
                            sys.stdin.read(1)
                        if code == "3":
                            return "DELETE"
                        if code == "5":
                            return "PGUP"
                        if code == "6":
                            return "PGDN"
            return ""
        return "ESC"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch in ("\x7f", "\x08"):
        return "BACKSPACE"
    if ch == "\x16":
        return "PASTE"
    if ch == "\x15":
        return "CLEAR_INPUT"
    if ch == "\x03":
        raise KeyboardInterrupt
    if raw_case:
        return ch
    if ch == " ":
        return "SPACE"
    return ch.lower()


# ---------------------------------------------------------------------------
# Styled Notification & Organize Views
# ---------------------------------------------------------------------------

def print_notification_panel(
    title: str,
    message: str,
    details: list = None,
    border_style: str = "bright_blue",
    footer_tip: str = "",
):
    """Render a consistent styled notification Panel matching the TUI visual language."""
    lines = [message]
    if details:
        lines.append("")
        for label, val in details:
            lines.append(f"  [bold cyan]• {label}:[/] {val}")
    if footer_tip:
        lines.append(f"\n[dim]💡 {footer_tip}[/]")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold magenta]🎬 Media Manager — {title}[/]",
        border_style=border_style,
        padding=(0, 2),
    )
    console.print(panel)


def build_organize_view(report: list, download_path: str, media_path: str, term_width: int = 120):
    """Build a styled Rich dashboard for the media organization report."""
    n_movies = sum(1 for r in report if r["kind"] == "movie" and r["status"] == "moved")
    n_episodes = sum(1 for r in report if r["kind"] == "episode" and r["status"] == "moved")
    n_subs = sum(1 for r in report if r["kind"] == "subtitle" and r["status"] == "moved")
    n_downloading = sum(1 for r in report if r["status"] == "downloading")
    n_skipped = sum(1 for r in report if r["status"] == "skipped")
    n_trash = sum(1 for r in report if r["status"] == "trashed")

    summary_parts = [
        f"[bold bright_green]🎬 Películas: {n_movies}[/]",
        f"[bold cyan]📺 Episodios: {n_episodes}[/]",
        f"[bold blue]💬 Subtítulos: {n_subs}[/]",
        f"[bold yellow]⏳ En descarga: {n_downloading}[/]",
    ]
    if n_skipped > 0:
        summary_parts.append(f"[dim]⏭ Omitidos: {n_skipped}[/]")
    if n_trash > 0:
        summary_parts.append(f"[dim]🗑 Papelera: {n_trash}[/]")

    header_panel = Panel(
        "   │   ".join(summary_parts),
        title="[bold magenta]🎬 Media Manager — Organizador de Medios[/]",
        border_style="magenta",
        padding=(0, 1),
    )

    compact = term_width < 95
    idx_w = 3
    kind_w = 12 if compact else 14
    status_w = 13 if compact else 16
    chrome_w = (5 * 3) + 1
    rem_w = max(28, term_width - (idx_w + kind_w + status_w + chrome_w))
    name_w = max(14, int(rem_w * 0.55))
    dest_w = max(14, rem_w - name_w)

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
    table.add_column("Archivo / Carpeta", min_width=name_w, max_width=name_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Tipo", width=kind_w, justify="left", no_wrap=True)
    table.add_column("Destino", min_width=dest_w, max_width=dest_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Estado", width=status_w, justify="left", no_wrap=True)

    if not report:
        table.add_row(
            "-",
            "[dim italic]No hay archivos pendientes en la carpeta de descargas[/]",
            "[dim]-[/]",
            "[dim]-[/]",
            "[bright_green]✔ Al día[/]",
        )
    else:
        for i, item in enumerate(report):
            kind = item.get("kind", "")
            status = item.get("status", "")
            if kind == "movie":
                kind_badge = "[bold magenta]🎬 Película[/]"
            elif kind == "episode":
                kind_badge = "[bold cyan]📺 Serie[/]"
            elif kind == "subtitle":
                kind_badge = "[bold blue]💬 Subtítulo[/]"
            elif kind == "downloading":
                kind_badge = "[bold yellow]⏳ Activo[/]"
            else:
                kind_badge = "[dim]🗑 Otro[/]"

            if status == "moved":
                status_badge = "[bold bright_green]✔ Organizado[/]"
            elif status == "downloading":
                status_badge = "[bold yellow]⏳ Descargando[/]"
            elif status == "skipped":
                status_badge = "[yellow]⏭ Ya existe[/]"
            elif status == "trashed":
                status_badge = "[dim]🗑 Papelera[/]"
            else:
                status_badge = status

            table.add_row(
                f"[dim]{i + 1:>2}[/]",
                f"[white]{item.get('name', '?')}[/]",
                kind_badge,
                f"[cyan]{item.get('target', '-')}[/]",
                status_badge,
            )

    footer_panel = Panel(
        f"📂 Origen: [cyan]{download_path}[/]   •   🎞 Biblioteca destino: [bold cyan]{media_path}[/]",
        border_style="cyan",
        padding=(0, 1),
    )
    return Group(header_panel, table, footer_panel)


# ---------------------------------------------------------------------------
# Interactive Torrent Search TUI
# ---------------------------------------------------------------------------

def _parse_size_to_bytes(size_str: str) -> float:
    """Parse human-readable size strings like '8.52 GiB' or '750 MB' into bytes for sorting."""
    if not size_str:
        return 0.0
    m = re.search(r"([\d.]+)\s*([KMGT]i?B|B)", str(size_str), re.IGNORECASE)
    if not m:
        return 0.0
    try:
        val = float(m.group(1))
    except ValueError:
        return 0.0
    unit = m.group(2).upper()
    multipliers = {
        "B": 1,
        "KB": 1024, "KIB": 1024,
        "MB": 1024 ** 2, "MIB": 1024 ** 2,
        "GB": 1024 ** 3, "GIB": 1024 ** 3,
        "TB": 1024 ** 4, "TIB": 1024 ** 4,
    }
    return val * multipliers.get(unit, 1)


def _fetch_pirate_results(query_str: str) -> tuple[list, str]:
    """Execute pirate-get in JSON mode and return (valid_items_list, error_message)."""
    pirate_cmd = get_pirate_command()
    res_Panel = Panel(
        f"[bold cyan]🔍 Buscando torrents para [/][bold bright_white]'{query_str}'[/][bold cyan]...[/]",
        title="[bold magenta]🎬 Media Manager — Buscador de Torrents[/]",
        border_style="magenta",
        padding=(0, 2),
    )
    with console.status(res_Panel, spinner="dots"):
        try:
            result = subprocess.run(
                [*pirate_cmd, query_str, "-j"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except subprocess.CalledProcessError:
            return [], f"No se encontraron resultados para '{query_str}'."
        except (FileNotFoundError, OSError) as e:
            return [], f"Error al ejecutar el buscador de torrents: {e}"

    if not result.stdout or not result.stdout.strip():
        return [], f"No se encontraron torrents para '{query_str}'."

    try:
        raw_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "No se pudo interpretar la respuesta del proveedor de búsqueda."

    items = []
    for raw in (raw_data or []):
        magnet = raw.get("magnet")
        if not magnet:
            continue
        seeders = int(raw.get("seeders", 0) or 0)
        leechers = int(raw.get("leechers", 0) or 0)
        size_str = str(raw.get("size", "Desconocido"))
        uploaded = str(raw.get("uploaded") or raw.get("date") or "-")
        items.append({
            "name": str(raw.get("name", "Unknown")),
            "size": size_str,
            "size_bytes": _parse_size_to_bytes(size_str),
            "seeders": seeders,
            "leechers": leechers,
            "uploaded": uploaded,
            "magnet": magnet,
        })

    if not items:
        return [], f"No se encontraron torrents válidos para '{query_str}'."
    return items, ""


def _render_health_badge(seeders: int, compact: bool = False) -> str:
    if seeders >= 20:
        return "[bold bright_green]● Alta[/]" if compact else "[bold bright_green]● Excelente[/]"
    elif seeders >= 5:
        return "[bold green]● Buena[/]"
    elif seeders >= 1:
        return "[bold yellow]● Baja[/]"
    return "[bold red]○ Sin seeds[/]"


def build_search_view(
    query_str: str,
    items: list,
    selected_idx: int = 0,
    checked_magnets: set = None,
    sort_mode: str = "seeders",
    input_mode: bool = False,
    input_buffer: str = "",
    feedback_msg: str = "",
    term_width: int = 120,
    term_height: int = 30,
):
    """Build the Rich renderable dashboard for the interactive Torrent Search TUI."""
    checked_magnets = checked_magnets or set()
    sort_labels = {
        "seeders": "Seeders ↓",
        "size": "Tamaño ↓",
        "name": "Nombre A-Z",
    }

    page_size = max(5, term_height - 13)
    total_items = len(items)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    cur_page = (selected_idx // page_size) + 1 if total_items > 0 else 1
    start_idx = (cur_page - 1) * page_size
    end_idx = min(total_items, start_idx + page_size)

    # 1. Header Summary Panel
    summary_parts = [
        f"[bold cyan]🔍 Búsqueda: \"{query_str}\"[/]",
        f"[bold green]📦 Resultados: {total_items}[/]",
        f"[bold bright_yellow]☑ Marcados: {len(checked_magnets)}[/]",
        f"[bold magenta]↕ Orden: {sort_labels.get(sort_mode, sort_mode)}[/]",
        f"[dim]📄 Pág {cur_page}/{total_pages}[/]",
    ]
    header_panel = Panel(
        "   │   ".join(summary_parts),
        title="[bold magenta]🎬 Media Manager — Buscador de Torrents[/]",
        border_style="magenta",
        padding=(0, 1),
    )

    # 2. Results Table with responsive column sizing
    compact = term_width < 95
    show_uploaded = term_width >= 115

    idx_w = 5
    health_w = 9 if compact else 12
    size_w = 11
    seeds_w = 8
    leech_w = 8
    up_w = 12 if show_uploaded else 0

    num_cols = 6 + (1 if show_uploaded else 0)
    chrome_w = (num_cols * 3) + 1
    fixed_w = idx_w + health_w + size_w + seeds_w + leech_w + up_w + chrome_w
    name_w = max(16, term_width - fixed_w)

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
    table.add_column("Nombre del Torrent", ratio=1, min_width=name_w, max_width=name_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Salud", width=health_w, justify="left", no_wrap=True)
    table.add_column("Tamaño", width=size_w, justify="right", no_wrap=True)
    table.add_column("Seeds", width=seeds_w, justify="right", no_wrap=True)
    table.add_column("Leech", width=leech_w, justify="right", no_wrap=True)
    if show_uploaded:
        table.add_column("Subido", width=up_w, justify="right", no_wrap=True)

    if not items:
        empty_row = ["-", "[dim italic]Sin resultados. Presioná [N] para buscar otro título.[/]", "-", "-", "-", "-"]
        if show_uploaded:
            empty_row.append("-")
        table.add_row(*empty_row)
    else:
        for i in range(start_idx, end_idx):
            it = items[i]
            is_sel = (i == selected_idx)
            is_chk = it["magnet"] in checked_magnets

            pointer = "▶" if is_sel else " "
            check_mark = "☑" if is_chk else " "
            if is_sel and is_chk:
                idx_cell = f"[bold bright_yellow]{pointer}☑{i + 1:>2}[/]"
            elif is_sel:
                idx_cell = f"[bold bright_yellow]{pointer} {i + 1:>2}[/]"
            elif is_chk:
                idx_cell = f"[bold bright_green] {check_mark}{i + 1:>2}[/]"
            else:
                idx_cell = f"[dim]  {i + 1:>2}[/]"

            if is_sel:
                name_cell = f"[bold bright_white]{it['name']}[/]"
            elif is_chk:
                name_cell = f"[bold bright_green]{it['name']}[/]"
            else:
                name_cell = f"[white]{it['name']}[/]"

            health_cell = _render_health_badge(it["seeders"], compact=compact)
            size_cell = f"[bold cyan]{it['size']}[/]"
            seeds_cell = f"[bold green]↑ {it['seeders']}[/]" if it["seeders"] > 0 else "[red]0[/]"
            leech_cell = f"[yellow]↓ {it['leechers']}[/]" if it["leechers"] > 0 else "[dim]0[/]"

            row_cells = [idx_cell, name_cell, health_cell, size_cell, seeds_cell, leech_cell]
            if show_uploaded:
                row_cells.append(f"[dim]{it['uploaded']}[/]")

            row_style = "on #1e293b" if is_sel else None
            table.add_row(*row_cells, style=row_style)

    # 3. Footer Inspector & Controls Panel
    footer_lines = []
    if items and 0 <= selected_idx < len(items):
        sel = items[selected_idx]
        ratio_str = f"{sel['seeders'] / sel['leechers']:.1f}" if sel["leechers"] > 0 else ("∞" if sel["seeders"] > 0 else "0.0")
        chk_status = " [bold bright_green](☑ MARCADO)[/]" if sel["magnet"] in checked_magnets else ""
        footer_lines.append(
            f"📌 [bold bright_white]{sel['name']}[/]{chk_status}\n"
            f"   Tamaño: [bold cyan]{sel['size']}[/]  •  "
            f"Seeders: [bold green]{sel['seeders']}[/]  •  "
            f"Leechers: [yellow]{sel['leechers']}[/]  •  "
            f"Ratio S/L: [magenta]{ratio_str}[/]  •  "
            f"Subido: [dim]{sel['uploaded']}[/]"
        )

    if input_mode:
        footer_lines.append(
            f"\n[bold yellow]🔍 Nueva búsqueda:[/] [bold bright_white]{input_buffer}█[/]   "
            f"[dim]([Enter] Buscar  •  [Esc] Cancelar)[/]"
        )
    elif feedback_msg:
        footer_lines.append(f"\n{feedback_msg}")

    dl_action_label = f"Descargar ({len(checked_magnets)} marcados)" if checked_magnets else "Descargar seleccionado"
    controls_line = (
        f"[bold cyan][↑/↓/PgUp/PgDn][/] Mover   "
        f"[bold bright_green][Enter][/] {dl_action_label}   "
        f"[bold yellow][Espacio][/] Marcar/Desmarcar (☑)   "
        f"[bold magenta][O][/] Ordenar   "
        f"[bold blue][N][/] Nueva búsqueda   "
        f"[bold white][Q / Esc][/] Volver"
    )
    footer_lines.append("\n" + controls_line)

    footer_panel = Panel(
        "\n".join(footer_lines),
        border_style="yellow" if input_mode else "cyan",
        padding=(0, 1),
    )

    return Group(header_panel, table, footer_panel)


def search_torrents_tui(initial_query: str) -> list:
    """
    Launch the interactive Torrent Search TUI.
    Returns a list of selected torrent dicts [{'name', 'size', 'seeders', 'magnet'}, ...].
    """
    current_query = initial_query.strip()
    items, err_msg = _fetch_pirate_results(current_query)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        if err_msg:
            print_notification_panel("Buscador de Torrents", f"[bold yellow]{err_msg}[/]", border_style="yellow")
            return []
        console.print(build_search_view(current_query, items, term_width=console.size.width))
        return []

    selected_idx = 0
    checked_magnets = set()
    by_magnet = {it["magnet"]: it for it in items}
    sort_modes = ["seeders", "size", "name"]
    sort_idx = 0
    input_mode = False
    input_buffer = ""
    feedback_msg = f"[bold yellow]⚠ {err_msg}[/]" if err_msg else ""
    feedback_until = time.monotonic() + 5.0 if err_msg else 0.0

    def set_feedback(msg: str, duration: float = 4.0):
        nonlocal feedback_msg, feedback_until
        feedback_msg = msg
        feedback_until = time.monotonic() + duration

    def apply_sort():
        nonlocal items, selected_idx
        mode = sort_modes[sort_idx]
        cur_mag = items[selected_idx]["magnet"] if items and 0 <= selected_idx < len(items) else None
        if mode == "seeders":
            items.sort(key=lambda x: (x["seeders"], x["size_bytes"]), reverse=True)
        elif mode == "size":
            items.sort(key=lambda x: x["size_bytes"], reverse=True)
        elif mode == "name":
            items.sort(key=lambda x: x["name"].lower())
        if cur_mag:
            for i, it in enumerate(items):
                if it["magnet"] == cur_mag:
                    selected_idx = i
                    break

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
    chosen_results = []

    try:
        with Live(
            build_search_view(
                current_query,
                items,
                selected_idx=selected_idx,
                checked_magnets=checked_magnets,
                sort_mode=sort_modes[sort_idx],
                input_mode=input_mode,
                input_buffer=input_buffer,
                feedback_msg=feedback_msg,
                term_width=console.size.width,
                term_height=console.size.height,
            ),
            console=console,
            auto_refresh=False,
            screen=True,
        ) as live:
            while True:
                now = time.monotonic()
                if feedback_msg and now >= feedback_until:
                    feedback_msg = ""

                live.update(
                    build_search_view(
                        current_query,
                        items,
                        selected_idx=selected_idx,
                        checked_magnets=checked_magnets,
                        sort_mode=sort_modes[sort_idx],
                        input_mode=input_mode,
                        input_buffer=input_buffer,
                        feedback_msg=feedback_msg,
                        term_width=console.size.width,
                        term_height=console.size.height,
                    ),
                    refresh=True,
                )

                key = read_key_fn(timeout=0.1, raw_case=input_mode)
                if not key:
                    continue

                if input_mode:
                    if key == "ESC":
                        input_mode = False
                        input_buffer = ""
                    elif key == "ENTER":
                        new_q = input_buffer.strip()
                        input_mode = False
                        input_buffer = ""
                        if new_q:
                            current_query = new_q
                            live.stop()
                            new_items, new_err = _fetch_pirate_results(current_query)
                            live.start()
                            items = new_items
                            for it in items:
                                by_magnet[it["magnet"]] = it
                            selected_idx = 0
                            apply_sort()
                            if new_err:
                                set_feedback(f"[bold yellow]⚠ {new_err}[/]")
                            else:
                                set_feedback(f"[bold bright_green]✔ Se encontraron {len(items)} resultados para '{current_query}'.[/]")
                    elif key in ("BACKSPACE", "DELETE"):
                        input_buffer = input_buffer[:-1]
                    elif key == "CLEAR_INPUT":
                        input_buffer = ""
                    elif key == "PASTE":
                        input_buffer += _get_clipboard_text()
                    elif key not in ("UP", "DOWN", "LEFT", "RIGHT", "HOME", "END", "PGUP", "PGDN"):
                        input_buffer += key
                    continue

                # Normal navigation & actions
                page_size = max(5, console.size.height - 13)

                if key in ("q", "ESC"):
                    chosen_results = []
                    break

                elif key in ("UP", "k", "w"):
                    if items:
                        selected_idx = (selected_idx - 1) % len(items)

                elif key in ("DOWN", "j", "s"):
                    if items:
                        selected_idx = (selected_idx + 1) % len(items)

                elif key == "PGUP":
                    if items:
                        selected_idx = max(0, selected_idx - page_size)

                elif key == "PGDN":
                    if items:
                        selected_idx = min(len(items) - 1, selected_idx + page_size)

                elif key == "HOME":
                    if items:
                        selected_idx = 0

                elif key == "END":
                    if items:
                        selected_idx = len(items) - 1

                elif key == "SPACE":
                    if items and 0 <= selected_idx < len(items):
                        mag = items[selected_idx]["magnet"]
                        if mag in checked_magnets:
                            checked_magnets.remove(mag)
                        else:
                            checked_magnets.add(mag)
                            by_magnet[mag] = items[selected_idx]

                elif key == "o":
                    sort_idx = (sort_idx + 1) % len(sort_modes)
                    apply_sort()
                    sort_names = {"seeders": "Seeders ↓", "size": "Tamaño ↓", "name": "Nombre A-Z"}
                    set_feedback(f"[bold magenta]↕ Ordenado por:[/] {sort_names[sort_modes[sort_idx]]}", duration=2.5)

                elif key == "n":
                    input_mode = True
                    input_buffer = ""

                elif key == "ENTER":
                    if checked_magnets:
                        chosen_results = [by_magnet[m] for m in checked_magnets if m in by_magnet]
                        break
                    elif items and 0 <= selected_idx < len(items):
                        chosen_results = [items[selected_idx]]
                        break

    except KeyboardInterrupt:
        chosen_results = []
    finally:
        if old_posix_settings is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_posix_settings)
            except Exception:
                pass

    return chosen_results


def search_interactive(query_str: str):
    """
    Runs the interactive torrent search TUI.
    Returns a list of selected magnet links (or None if cancelled) — compatible with single or multi-select.
    """
    chosen = search_torrents_tui(query_str)
    if not chosen:
        return None
    if len(chosen) == 1:
        return chosen[0]["magnet"]
    return [c["magnet"] for c in chosen]


# ---------------------------------------------------------------------------
# Interactive Download Manager Viewer TUI
# ---------------------------------------------------------------------------

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
                        rep = organize_downloads(cfg["download_path"], cfg["media_path"], quiet=True)
                        moved_n = sum(1 for r in rep if r["status"] == "moved")
                        set_feedback(f"[bold bright_green]📁 Organización completada ({moved_n} archivo(s) movido(s)).[/]")
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


# ---------------------------------------------------------------------------
# Main Interactive Menu Dashboard TUI
# ---------------------------------------------------------------------------

MENU_ITEMS = [
    {
        "id": "search",
        "icon": "🔍",
        "title": "Buscar Películas y Series",
        "desc": "Buscar torrents interactivamente y ponerlos a descargar",
        "shortcut": "[1 / B]",
    },
    {
        "id": "status",
        "icon": "📊",
        "title": "Visor y Gestor de Descargas",
        "desc": "Ver progreso en vivo, tamaño, pausar, eliminar o hacer clear",
        "shortcut": "[2 / V]",
    },
    {
        "id": "add",
        "icon": "🧲",
        "title": "Agregar Enlace Magnet o .torrent",
        "desc": "Pegar enlace magnet, URL directa o ruta a un archivo .torrent",
        "shortcut": "[3 / M]",
    },
    {
        "id": "organize",
        "icon": "📁",
        "title": "Organizar Descargas Manualmente",
        "desc": "Clasificar descargas completadas en carpetas Movies y Shows",
        "shortcut": "[4 / O]",
    },
    {
        "id": "clear",
        "icon": "🧹",
        "title": "Limpiar Descargas Completadas",
        "desc": "Hacer clear de todas las descargas finalizadas del historial",
        "shortcut": "[5 / C]",
    },
    {
        "id": "exit",
        "icon": "❌",
        "title": "Salir",
        "desc": "Cerrar Media Manager (las descargas siguen en segundo plano)",
        "shortcut": "[6 / Q]",
    },
]


def build_main_menu_view(
    downloads: list,
    config: dict,
    selected_idx: int = 0,
    prompt_mode: str = None,
    prompt_buffer: str = "",
    feedback_msg: str = "",
    term_width: int = 120,
):
    """Build the Rich renderable dashboard for the Main Interactive Menu."""
    from .downloader import format_speed

    active_count = sum(1 for d in downloads if d["status"] == "active")
    inactive_count = sum(1 for d in downloads if d["status"] in ("paused", "waiting"))
    complete_count = sum(1 for d in downloads if d["status"] == "complete")
    total_dl_speed = sum(d["speed"] for d in downloads if d["status"] == "active")

    # 1. Header Panel with live aria2c metrics
    summary_parts = [
        "[bold bright_green]🟢 Daemon aria2c: Activo[/]",
        f"[bold green]● Activas: {active_count}[/]",
        f"[bold yellow]⏸ En pausa: {inactive_count}[/]",
        f"[bold bright_green]✔ Completadas: {complete_count}[/]",
        f"[bold cyan]⬇ {format_speed(total_dl_speed)}[/]",
    ]
    header_panel = Panel(
        "   │   ".join(summary_parts),
        title="[bold magenta]🎬 Media Manager — Panel Principal[/]",
        border_style="magenta",
        padding=(0, 1),
    )

    # 2. Menu Options Table
    compact = term_width < 95
    idx_w = 3
    short_w = 8
    chrome_w = (4 * 3) + 1
    rem_w = max(30, term_width - (idx_w + short_w + chrome_w))
    title_w = min(36, max(22, int(rem_w * 0.42)))
    desc_w = max(16, rem_w - title_w)

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
    table.add_column("Acción", width=title_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Descripción", ratio=1, min_width=desc_w, max_width=desc_w, overflow="ellipsis", no_wrap=True)
    table.add_column("Atajo", width=short_w, justify="center", no_wrap=True)

    for i, item in enumerate(MENU_ITEMS):
        is_sel = (i == selected_idx)
        idx_cell = f"[bold bright_yellow]▶ {i + 1}[/]" if is_sel else f"[dim]  {i + 1}[/]"
        if is_sel:
            title_cell = f"{item['icon']} [bold bright_white]{item['title']}[/]"
            desc_cell = f"[bright_white]{item['desc']}[/]"
            short_cell = f"[bold bright_yellow]{item['shortcut']}[/]"
        else:
            title_cell = f"{item['icon']} [white]{item['title']}[/]"
            desc_cell = f"[dim]{item['desc']}[/]"
            short_cell = f"[cyan]{item['shortcut']}[/]"

        row_style = "on #1e293b" if is_sel else None
        table.add_row(idx_cell, title_cell, desc_cell, short_cell, style=row_style)

    # 3. Footer Inspector / Input Modal & Controls Panel
    footer_lines = [
        f"📂 Carpeta Descargas: [cyan]{config.get('download_path', '')}[/]   •   "
        f"🎞 Biblioteca Media: [bold cyan]{config.get('media_path', '')}[/]"
    ]

    if prompt_mode == "search":
        footer_lines.append(
            f"\n[bold yellow]🔍 Ingresá tu búsqueda:[/] [bold bright_white]{prompt_buffer}█[/]   "
            f"[dim]([Enter] Buscar  •  [Ctrl+V] Pegar  •  [Esc] Cancelar)[/]"
        )
    elif prompt_mode == "add":
        footer_lines.append(
            f"\n[bold yellow]🧲 Enlace Magnet o ruta .torrent:[/] [bold bright_white]{prompt_buffer}█[/]   "
            f"[dim]([Enter] Agregar  •  [Ctrl+V] Pegar  •  [Esc] Cancelar)[/]"
        )
    elif feedback_msg:
        footer_lines.append(f"\n{feedback_msg}")

    controls_line = (
        "[bold cyan][↑/↓ / 1-6][/] Seleccionar   "
        "[bold bright_green][Enter][/] Abrir   "
        "[bold yellow][B][/] Buscar   "
        "[bold magenta][V][/] Visor Descargas   "
        "[bold blue][M][/] Agregar Magnet   "
        "[bold white][Q / Esc][/] Salir"
    )
    footer_lines.append("\n" + controls_line)

    footer_panel = Panel(
        "\n".join(footer_lines),
        border_style="yellow" if prompt_mode else "cyan",
        padding=(0, 1),
    )

    return Group(header_panel, table, footer_panel)


def show_main_menu_tui():
    """Launch the cohesive interactive Main Dashboard TUI for Media Manager."""
    from .downloader import (
        ensure_daemon,
        get_all_downloads,
        add_download,
        clear_completed_downloads,
    )
    from .organizer import organize_downloads

    try:
        ensure_daemon(quiet=True)
    except Exception:
        pass

    config = load_config()
    selected_idx = 0
    prompt_mode = None
    prompt_buffer = ""
    feedback_msg = ""
    feedback_until = 0.0

    def set_feedback(msg: str, duration: float = 5.0):
        nonlocal feedback_msg, feedback_until
        feedback_msg = msg
        feedback_until = time.monotonic() + duration

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

    def execute_menu_action(action_id: str, live: Live) -> bool:
        """Execute a menu option; returns False if the user chose to exit."""
        nonlocal prompt_mode, prompt_buffer, downloads, last_fetch
        if action_id == "exit":
            return False
        elif action_id == "search":
            prompt_mode = "search"
            prompt_buffer = ""
        elif action_id == "add":
            prompt_mode = "add"
            prompt_buffer = ""
        elif action_id == "status":
            live.stop()
            show_downloads_tui()
            live.start()
            downloads = get_all_downloads()
            last_fetch = time.monotonic()
        elif action_id == "organize":
            try:
                rep = organize_downloads(config["download_path"], config["media_path"], quiet=True)
                moved_n = sum(1 for r in rep if r["status"] == "moved")
                dl_n = sum(1 for r in rep if r["status"] == "downloading")
                if moved_n > 0:
                    set_feedback(f"[bold bright_green]📁 Se organizaron {moved_n} archivo(s) en tu biblioteca multimedia.[/]")
                elif dl_n > 0:
                    set_feedback(f"[bold yellow]⏳ No hay descargas terminadas por mover ({dl_n} sigue(n) descargando).[/]")
                else:
                    set_feedback("[cyan]ℹ La carpeta de descargas ya está limpia y organizada.[/]")
            except Exception as e:
                set_feedback(f"[bold red]✖ Error al organizar:[/] {e}")
        elif action_id == "clear":
            completed_items = [d for d in downloads if d["status"] == "complete"]
            if not completed_items:
                set_feedback("[yellow]ℹ No hay descargas completadas para limpiar.[/]")
            else:
                count = clear_completed_downloads()
                cleared_n = max(count, len(completed_items))
                set_feedback(f"[bold bright_green]✨ Se limpiaron {cleared_n} descarga(s) completada(s).[/]")
                downloads = get_all_downloads()
                last_fetch = time.monotonic()
        return True

    try:
        downloads = get_all_downloads()
        last_fetch = time.monotonic()

        with Live(
            build_main_menu_view(
                downloads,
                config,
                selected_idx=selected_idx,
                prompt_mode=prompt_mode,
                prompt_buffer=prompt_buffer,
                feedback_msg=feedback_msg,
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

                if now - last_fetch >= 1.0:
                    downloads = get_all_downloads()
                    last_fetch = time.monotonic()

                live.update(
                    build_main_menu_view(
                        downloads,
                        config,
                        selected_idx=selected_idx,
                        prompt_mode=prompt_mode,
                        prompt_buffer=prompt_buffer,
                        feedback_msg=feedback_msg,
                        term_width=console.size.width,
                    ),
                    refresh=True,
                )

                key = read_key_fn(timeout=0.1, raw_case=bool(prompt_mode))
                if not key:
                    continue

                if prompt_mode is not None:
                    if key == "ESC":
                        prompt_mode = None
                        prompt_buffer = ""
                    elif key == "ENTER":
                        submitted = prompt_buffer.strip()
                        mode = prompt_mode
                        prompt_mode = None
                        prompt_buffer = ""
                        if not submitted:
                            continue
                        if mode == "search":
                            live.stop()
                            chosen = search_torrents_tui(submitted)
                            live.start()
                            if chosen:
                                added_names = []
                                for c in chosen:
                                    try:
                                        add_download(c["magnet"], config["download_path"], quiet=True)
                                        added_names.append(c["name"])
                                    except Exception as e:
                                        set_feedback(f"[bold red]✖ Error al agregar descarga:[/] {e}")
                                if added_names:
                                    if len(added_names) == 1:
                                        set_feedback(f"[bold bright_green]✓ Descarga agregada:[/] [white]{added_names[0]}[/]  [dim](Presioná [V] para ver progreso)[/]")
                                    else:
                                        set_feedback(f"[bold bright_green]✓ Se agregaron {len(added_names)} descargas a la cola.[/]  [dim](Presioná [V] para ver progreso)[/]")
                            else:
                                set_feedback("[dim]Búsqueda finalizada sin seleccionar descargas.[/]", duration=2.5)
                            downloads = get_all_downloads()
                            last_fetch = time.monotonic()
                        elif mode == "add":
                            try:
                                gid = add_download(submitted, config["download_path"], quiet=True)
                                set_feedback(f"[bold bright_green]✓ Descarga agregada (GID: {gid}).[/]  [dim](Presioná [V] para ver progreso)[/]")
                            except Exception as e:
                                set_feedback(f"[bold red]✖ Error al agregar descarga:[/] {e}")
                            downloads = get_all_downloads()
                            last_fetch = time.monotonic()
                    elif key in ("BACKSPACE", "DELETE"):
                        prompt_buffer = prompt_buffer[:-1]
                    elif key == "CLEAR_INPUT":
                        prompt_buffer = ""
                    elif key == "PASTE":
                        prompt_buffer += _get_clipboard_text()
                    elif key not in ("UP", "DOWN", "LEFT", "RIGHT", "HOME", "END", "PGUP", "PGDN"):
                        prompt_buffer += key
                    continue

                # Menu navigation & hotkeys
                if key in ("q", "ESC"):
                    break
                elif key in ("UP", "k", "w"):
                    selected_idx = (selected_idx - 1) % len(MENU_ITEMS)
                elif key in ("DOWN", "j", "s"):
                    selected_idx = (selected_idx + 1) % len(MENU_ITEMS)
                elif key == "HOME":
                    selected_idx = 0
                elif key == "END":
                    selected_idx = len(MENU_ITEMS) - 1
                elif key in ("1", "2", "3", "4", "5", "6"):
                    selected_idx = int(key) - 1
                    if not execute_menu_action(MENU_ITEMS[selected_idx]["id"], live):
                        break
                elif key == "b":
                    selected_idx = 0
                    execute_menu_action("search", live)
                elif key == "v":
                    selected_idx = 1
                    execute_menu_action("status", live)
                elif key == "m":
                    selected_idx = 2
                    execute_menu_action("add", live)
                elif key == "o":
                    selected_idx = 3
                    execute_menu_action("organize", live)
                elif key == "c":
                    selected_idx = 4
                    execute_menu_action("clear", live)
                elif key == "ENTER":
                    if not execute_menu_action(MENU_ITEMS[selected_idx]["id"], live):
                        break

    except KeyboardInterrupt:
        pass
    finally:
        if old_posix_settings is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_posix_settings)
            except Exception:
                pass
