import click
import subprocess
import time
from .config import load_config
from .organizer import organize_downloads
from .downloader import add_download

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
        from .downloader import ensure_daemon
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
                questionary.Choice("📊 View Active Downloads", value="status"),
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
        from .config import load_config
        from .downloader import add_download
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
def status():
    """Show the current download status."""
    from .downloader import ensure_daemon
    try:
        ensure_daemon()
    except Exception as e:
        click.echo(f"Error starting aria2c: {e}")
        return

    from .tui import get_binary_path
    aria2p_bin = get_binary_path("aria2p")
    proc = subprocess.run([aria2p_bin, "top"])
    if proc.returncode != 0:
        # Fallback to rich table if aria2p fails to open or is not available
        try:
            from .downloader import get_active_downloads
            from rich.console import Console
            from rich.table import Table
            console = Console()
            dls = get_active_downloads()
            if not dls:
                console.print("[bold yellow]No active downloads.[/]")
                return
            table = Table(title="Active Downloads", show_header=True, header_style="bold cyan")
            table.add_column("GID", style="dim")
            table.add_column("Name", style="green")
            table.add_column("Progress", justify="right")
            table.add_column("Speed", justify="right")
            table.add_column("Status")
            for d in dls:
                speed = d["speed"]
                speed_str = f"{speed / 1024:.1f} KB/s" if speed < 1024*1024 else f"{speed / (1024*1024):.2f} MB/s"
                table.add_row(d["gid"], str(d["name"]), f"{d['progress']}%", speed_str, d["status"])
            console.print(table)
        except Exception as e:
            click.echo(f"Error checking download status: {e}")

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
        
        # aria2c passes 0 for num_files if the download is a single file, actually the docs say it passes the number of files.
        # If the download has no files, we do nothing.
        if num_files == "0":
            return
            
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
            log_dir = os.path.expanduser("~/.config/media_manager")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "hook.log")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().isoformat()}] GID: {gid} PATH: {path} ERROR: {e}\n")
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass

if __name__ == '__main__':
    cli()
