import sys
import click
from .config import load_config, get_config_dir
from .tui import _ensure_utf8_console

_ensure_utf8_console()
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
        from rich.console import Console
        console = Console()
        console.print(f"Adding download to [cyan]{dl_path}[/]...")
        try:
            add_download(file_input, dl_path)
            console.print("[bold green]✓ Download added successfully to detached aria2 daemon.[/]")
        except Exception as e:
            console.print(f"[bold red]Error adding download:[/] {e}")
        return

    if ctx.invoked_subcommand is None:
        # No command was passed, show the main interactive menu
        try:
            ensure_daemon()
        except Exception:
            pass

        import questionary
        from rich.console import Console
        console = Console()
        
        console.print("[bold magenta]🎬 Welcome to Media Manager[/bold magenta]\n")
        
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("🔍 Search for Media", value="search"),
                questionary.Choice("🧲 Add Magnet Link / Torrent File", value="add"),
                questionary.Choice("📊 View & Manage Downloads", value="status"),
                questionary.Choice("🧹 Clear Completed Downloads", value="clear"),
                questionary.Choice("📁 Organize Downloads Manually", value="organize"),
                questionary.Choice("❌ Exit", value="exit")
            ],
            style=questionary.Style([
                ('qmark', 'fg:#ff9d00 bold'),
                ('question', 'bold'),
                ('answer', 'fg:#ff9d00 bold'),
                ('pointer', 'fg:#ff9d00 bold'),
                ('highlighted', 'fg:#ff9d00 bold'),
                ('selected', 'fg:#cc5454'),
            ])
        ).ask()
        
        if action == "exit" or action is None:
            return
            
        if action == "search":
            query = questionary.text("Enter your search query:").ask()
            if query:
                ctx.invoke(search, query=(query,))
        elif action == "add":
            target = questionary.text("Enter magnet link or path to .torrent file:").ask()
            if target:
                ctx.invoke(download, uri=target)
        elif action == "status":
            ctx.invoke(status)
        elif action == "clear":
            ctx.invoke(clear)
        elif action == "organize":
            ctx.invoke(organize)


@cli.command()
@click.pass_context
@click.argument('query', nargs=-1)
def search(ctx, query):
    """Search for torrents and assign them to the downloader."""
    if not query:
        click.echo("Please provide a search query.")
        return
    query_str = " ".join(query)
    from .tui import search_interactive
    from rich.console import Console
    console = Console()
    
    magnet = search_interactive(query_str)
    
    if magnet:
        console.print("\n[bold green]✓ Torrent selected![/]")
        config = load_config()
        dl_path = config["download_path"]
        console.print(f"Adding download to {dl_path}...")
        add_download(magnet, dl_path)
        console.print("Download added to detached aria2 daemon.")
    else:
        console.print("\n[bold yellow]Search cancelled or finished.[/]")


@cli.command()
@click.argument('uri')
def download(uri):
    """Command to add a download (magnet link, URL, or .torrent file)."""
    config = load_config()
    dl_path = config["download_path"]
    
    click.echo(f"Adding download to {dl_path}...")
    try:
        add_download(uri, dl_path)
        click.echo("Download added to detached aria2 daemon.")
    except Exception as e:
        click.echo(f"Error adding download: {e}")


@cli.command()
@click.option('--once', is_flag=True, help='Print a static snapshot of downloads and exit.')
def status(once):
    """Open the interactive Download Manager viewer (progress, size, pause, delete, clear)."""
    try:
        ensure_daemon()
    except Exception as e:
        click.echo(f"Error starting aria2c: {e}")
        return

    from .tui import show_downloads_tui, build_downloads_view, console
    if once:
        downloads = get_all_downloads()
        console.print(build_downloads_view(downloads, interactive=False, term_width=console.size.width))
        return

    show_downloads_tui()


@cli.command()
@click.argument('target', required=False, default="all")
def pause(target):
    """Pause a specific download (by #, GID, or name) or 'all'."""
    from rich.console import Console
    console = Console()
    try:
        ensure_daemon()
        if target.lower() == "all":
            pause_all_downloads()
            console.print("[bold yellow]⏸ Todas las descargas activas fueron puestas en pausa.[/]")
        else:
            item = _resolve_target_gid(target)
            pause_download(item["gid"])
            console.print(f"[bold yellow]⏸ Descarga en pausa:[/] {item['name']} ([dim]{item['gid']}[/])")
    except Exception as e:
        console.print(f"[bold red]Error al pausar descarga:[/] {e}")


@cli.command()
@click.argument('target', required=False, default="all")
def resume(target):
    """Resume a paused download (by #, GID, or name) or 'all'."""
    from rich.console import Console
    console = Console()
    try:
        ensure_daemon()
        if target.lower() == "all":
            resume_all_downloads()
            console.print("[bold green]▶ Todas las descargas en pausa fueron reanudadas.[/]")
        else:
            item = _resolve_target_gid(target)
            resume_download(item["gid"])
            console.print(f"[bold green]▶ Descarga reanudada:[/] {item['name']} ([dim]{item['gid']}[/])")
    except Exception as e:
        console.print(f"[bold red]Error al reanudar descarga:[/] {e}")


@cli.command()
@click.argument('target')
def remove(target):
    """Remove/delete a specific download (by #, GID, or name)."""
    from rich.console import Console
    console = Console()
    try:
        ensure_daemon()
        item = _resolve_target_gid(target)
        remove_download(item["gid"], delete_files=True)
        console.print(f"[bold green]🗑 Descarga eliminada:[/] {item['name']} ([dim]{item['gid']}[/])")
    except Exception as e:
        console.print(f"[bold red]Error al eliminar descarga:[/] {e}")


@cli.command()
def clear():
    """Clear all completed downloads from the download viewer."""
    from rich.console import Console
    console = Console()
    try:
        ensure_daemon()
        count = clear_completed_downloads()
        console.print(f"[bold bright_green]✨ Se limpiaron las descargas completadas ({count} eliminada(s) del historial).[/]")
    except Exception as e:
        console.print(f"[bold red]Error al limpiar descargas completadas:[/] {e}")


@cli.command()
def organize():
    """Manually organize completed downloads."""
    config = load_config()
    dl_path = config["download_path"]
    media_path = config["media_path"]
    
    click.echo(f"Organizing downloads from {dl_path} into {media_path}...")
    organize_downloads(dl_path, media_path)
    click.echo("Done.")


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
