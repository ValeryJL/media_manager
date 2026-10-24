import sys
import click
from .config import load_config, get_config_dir
from .organizer import organize_downloads
from .downloader import (
    add_download,
    ensure_daemon,
    get_all_downloads,
    pause_download,
    resume_download,
    pause_all_downloads,
    resume_all_downloads,
    remove_download,
    clear_completed_downloads,
    record_completed_download,
)
from .tui import (
    _ensure_utf8_console,
    console,
    show_main_menu_tui,
    show_downloads_tui,
    search_torrents_tui,
    build_downloads_view,
    build_organize_view,
    print_notification_panel,
)

_ensure_utf8_console()


def _resolve_target_gid(identifier: str) -> dict:
    """Resolve a download by 1-based index, exact GID, GID prefix, or substring of name."""
    dls = get_all_downloads()
    if not dls:
        raise ValueError("No hay descargas en la lista.")

    ident = identifier.strip()
    if ident.isdigit():
        idx = int(ident) - 1
        if 0 <= idx < len(dls):
            return dls[idx]

    for d in dls:
        if d["gid"].lower() == ident.lower():
            return d

    for d in dls:
        if d["gid"].lower().startswith(ident.lower()):
            return d

    for d in dls:
        if ident.lower() in d["name"].lower():
            return d

    raise ValueError(f"No se encontró ninguna descarga que coincida con '{identifier}'.")


@click.group(invoke_without_command=True)
@click.option('-f', '--file', 'file_input', type=str, help='Path to a .torrent file or magnet link to download.')
@click.pass_context
def cli(ctx, file_input):
    """Media Manager CLI: Search, Download, and Organize your media automatically."""
    if file_input:
        config = load_config()
        dl_path = config["download_path"]
        try:
            gid = add_download(file_input, dl_path, quiet=True)
            print_notification_panel(
                "Nueva Descarga",
                "[bold bright_green]✔ Descarga agregada correctamente al daemon aria2c en segundo plano.[/]",
                details=[
                    ("GID", f"[bold white]{gid}[/]"),
                    ("Origen", f"[white]{file_input[:80] + ('...' if len(file_input) > 80 else '')}[/]"),
                    ("Carpeta de descarga", f"[cyan]{dl_path}[/]"),
                ],
                border_style="bright_green",
                footer_tip="Ejecutá 'media-manager status' para ver el progreso en tiempo real.",
            )
        except Exception as e:
            print_notification_panel(
                "Error al Agregar Descarga",
                f"[bold red]✖ No se pudo agregar la descarga:[/] {e}",
                border_style="red",
            )
        return

    if ctx.invoked_subcommand is None:
        show_main_menu_tui()


@cli.command()
@click.pass_context
@click.argument('query', nargs=-1)
def search(ctx, query):
    """Search for torrents and assign them to the downloader."""
    if not query:
        print_notification_panel(
            "Buscador de Torrents",
            "[bold yellow]⚠ Por favor indicá un término de búsqueda (ej. 'media-manager search Dexter').[/]",
            border_style="yellow",
        )
        return

    query_str = " ".join(query)
    chosen = search_torrents_tui(query_str)

    if chosen:
        config = load_config()
        dl_path = config["download_path"]
        added_details = []
        for item in chosen:
            try:
                gid = add_download(item["magnet"], dl_path, quiet=True)
                added_details.append((item["name"], f"[bold bright_green]GID: {gid}[/] [dim]({item['size']})[/]"))
            except Exception as e:
                added_details.append((item["name"], f"[bold red]Error: {e}[/]"))

        added_Details_with_dir = added_details + [("Carpeta destino", f"[cyan]{dl_path}[/]")]
        print_notification_panel(
            "Descargas Agregadas",
            f"[bold bright_green]✔ Se enviaron {len(chosen)} torrent(s) al daemon de aria2c.[/]",
            details=added_Details_with_dir,
            border_style="bright_green",
            footer_tip="Ejecutá 'media-manager status' para ver el progreso y gestionar las descargas.",
        )
    else:
        print_notification_panel(
            "Buscador de Torrents",
            "[dim]Búsqueda cancelada o finalizada sin seleccionar descargas.[/]",
            border_style="cyan",
        )


@cli.command()
@click.argument('uri')
def download(uri):
    """Command to add a download (magnet link, URL, or .torrent file)."""
    config = load_config()
    dl_path = config["download_path"]

    try:
        gid = add_download(uri, dl_path, quiet=True)
        print_notification_panel(
            "Nueva Descarga",
            "[bold bright_green]✔ Descarga agregada correctamente al daemon aria2c en segundo plano.[/]",
            details=[
                ("GID", f"[bold white]{gid}[/]"),
                ("Origen", f"[white]{uri[:80] + ('...' if len(uri) > 80 else '')}[/]"),
                ("Carpeta de descarga", f"[cyan]{dl_path}[/]"),
            ],
            border_style="bright_green",
            footer_tip="Ejecutá 'media-manager status' para ver el progreso en tiempo real.",
        )
    except Exception as e:
        print_notification_panel(
            "Error al Agregar Descarga",
            f"[bold red]✖ No se pudo agregar la descarga:[/] {e}",
            border_style="red",
        )


@cli.command()
@click.option('--once', is_flag=True, help='Print a static snapshot of downloads and exit.')
def status(once):
    """Open the interactive Download Manager viewer (progress, size, pause, delete, clear)."""
    try:
        ensure_daemon(quiet=True)
    except Exception as e:
        print_notification_panel(
            "Error de Daemon",
            f"[bold red]✖ No se pudo iniciar aria2c:[/] {e}",
            border_style="red",
        )
        return

    if once:
        downloads = get_all_downloads()
        console.print(build_downloads_view(downloads, interactive=False, term_width=console.size.width))
        return

    show_downloads_tui()


@cli.command()
@click.argument('target', required=False, default="all")
def pause(target):
    """Pause a specific download (by #, GID, or name) or 'all'."""
    try:
        ensure_daemon(quiet=True)
        if target.lower() == "all":
            pause_all_downloads()
            print_notification_panel(
                "Gestión de Descargas",
                "[bold yellow]⏸ Todas las descargas activas fueron puestas en pausa.[/]",
                border_style="yellow",
            )
        else:
            item = _resolve_target_gid(target)
            pause_download(item["gid"])
            print_notification_panel(
                "Gestión de Descargas",
                "[bold yellow]⏸ Descarga puesta en pausa correctamente.[/]",
                details=[
                    ("Nombre", f"[white]{item['name']}[/]"),
                    ("GID", f"[dim]{item['gid']}[/]"),
                    ("Estado", "[bold yellow]⏸ Inactivo (Pausa)[/]"),
                ],
                border_style="yellow",
            )
    except Exception as e:
        print_notification_panel("Error al Pausar", f"[bold red]✖ {e}[/]", border_style="red")


@cli.command()
@click.argument('target', required=False, default="all")
def resume(target):
    """Resume a paused download (by #, GID, or name) or 'all'."""
    try:
        ensure_daemon(quiet=True)
        if target.lower() == "all":
            resume_all_downloads()
            print_notification_panel(
                "Gestión de Descargas",
                "[bold bright_green]▶ Todas las descargas en pausa fueron reanudadas.[/]",
                border_style="bright_green",
            )
        else:
            item = _resolve_target_gid(target)
            resume_download(item["gid"])
            print_notification_panel(
                "Gestión de Descargas",
                "[bold bright_green]▶ Descarga reanudada correctamente.[/]",
                details=[
                    ("Nombre", f"[white]{item['name']}[/]"),
                    ("GID", f"[dim]{item['gid']}[/]"),
                    ("Estado", "[bold green]● Activo[/]"),
                ],
                border_style="bright_green",
            )
    except Exception as e:
        print_notification_panel("Error al Reanudar", f"[bold red]✖ {e}[/]", border_style="red")


@cli.command()
@click.argument('target')
def remove(target):
    """Remove/delete a specific download (by #, GID, or name)."""
    try:
        ensure_daemon(quiet=True)
        item = _resolve_target_gid(target)
        remove_download(item["gid"], delete_files=True)
        print_notification_panel(
            "Gestión de Descargas",
            "[bold bright_green]🗑 Descarga eliminada correctamente.[/]",
            details=[
                ("Nombre", f"[white]{item['name']}[/]"),
                ("GID", f"[dim]{item['gid']}[/]"),
            ],
            border_style="bright_green",
        )
    except Exception as e:
        print_notification_panel("Error al Eliminar", f"[bold red]✖ {e}[/]", border_style="red")


@cli.command()
def clear():
    """Clear all completed downloads from the download viewer."""
    try:
        ensure_daemon(quiet=True)
        count = clear_completed_downloads()
        print_notification_panel(
            "Limpieza de Historial",
            f"[bold bright_green]✨ Se limpiaron las descargas completadas ({count} entrada(s) eliminada(s)).[/]",
            border_style="bright_green",
        )
    except Exception as e:
        print_notification_panel("Error al Limpiar", f"[bold red]✖ {e}[/]", border_style="red")


@cli.command()
def organize():
    """Manually organize completed downloads."""
    config = load_config()
    dl_path = config["download_path"]
    media_path = config["media_path"]

    report = organize_downloads(dl_path, media_path, quiet=True)
    console.print(build_organize_view(report, dl_path, media_path, term_width=console.size.width))


@cli.command()
@click.argument('uri', required=False, default=None)
@click.option('--install-shortcut', is_flag=True, help='Install or update the system Desktop / Start Menu shortcut.')
@click.option('--wait', is_flag=True, help='Run the GUI in the foreground instead of detaching.')
def gui(uri, install_shortcut, wait):
    """Launch the cross-platform Flutter Desktop GUI application."""
    from .gui import launch_gui, spawn_gui_detached, install_desktop_shortcut

    if install_shortcut:
        paths = install_desktop_shortcut()
        if paths:
            details = [(f"Acceso directo {i + 1}", f"[cyan]{p}[/]") for i, p in enumerate(paths)]
            print_notification_panel(
                "Instalación de App de Escritorio",
                "[bold bright_green]✔ Aplicación Media Manager registrada en el sistema correctamente.[/]",
                details=details,
                border_style="bright_green",
                footer_tip="Ya podés abrir 'Media Manager' desde el Menú Inicio, Escritorio o lanzador del sistema.",
            )
        else:
            print_notification_panel(
                "Error de Acceso Directo",
                "[bold red]✖ No se pudieron crear los accesos directos en el sistema.[/]",
                border_style="red",
            )
        return

    if wait:
        launch_gui(initial_uri=uri)
    else:
        if spawn_gui_detached(initial_uri=uri):
            print_notification_panel(
                "Media Manager Desktop GUI (Flutter)",
                "[bold bright_green]🖥️ Ventana de escritorio iniciada en segundo plano.[/]",
                details=[
                    ("Motor gráfico", "[bold bright_cyan]Flutter Desktop (Flet)[/]"),
                    ("Daemon RPC", "[bold green]aria2c (localhost:6800)[/]"),
                ],
                border_style="bright_green",
                footer_tip="Podés cerrar esta terminal; la aplicación de escritorio seguirá abierta de forma independiente.",
            )
        else:
            launch_gui(initial_uri=uri)


@cli.command()
@click.argument('gid')
@click.argument('num_files')
@click.argument('path')
def hook(gid, num_files, path):
    """Hidden command called by aria2c on download complete."""
    try:
        config = load_config()
        media_path = config["media_path"]
        dl_path = config["download_path"]
        
        if num_files == "0":
            return

        # Record completed download in persistent history before moving files
        try:
            record_completed_download(gid, path)
        except Exception:
            pass
            
        from pathlib import Path
        from .organizer import process_item
        
        item_path = Path(path).resolve()
        dl_dir = Path(dl_path).resolve()
        
        # Try to find the top-level item inside dl_path (e.g. the folder containing torrent files)
        try:
            rel_path = item_path.relative_to(dl_dir)
            top_level_name = rel_path.parts[0]
            item_to_process = dl_dir / top_level_name
        except ValueError:
            # If it's outside dl_path or just a file in dl_path directly, process the path itself
            item_to_process = item_path

        if item_to_process.exists():
            trash_dir = Path(media_path) / ".trash"
            process_item(item_to_process, Path(media_path), trash_dir)
    except Exception as e:
        import os
        import datetime
        import traceback
        try:
            log_dir = str(get_config_dir())
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "hook.log")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().isoformat()}] GID: {gid} PATH: {path} ERROR: {e}\n")
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass


if __name__ == '__main__':
    cli()
