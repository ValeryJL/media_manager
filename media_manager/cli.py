import click
import subprocess
import time
from .config import load_config
from .organizer import organize_downloads
from .downloader import add_download

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Media Manager CLI: Search, Download, and Organize your media automatically."""
    if ctx.invoked_subcommand is None:
        # No command was passed, show the main interactive menu
        import questionary
        from rich.console import Console
        console = Console()
        
        console.print("[bold magenta]🎬 Welcome to Media Manager[/bold magenta]\n")
        
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("🔍 Search for Media", value="search"),
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
    """Hidden command used by pirate-get to add a download."""
    config = load_config()
    dl_path = config["download_path"]
    
    click.echo(f"Adding download to {dl_path}...")
    add_download(uri, dl_path)
    click.echo("Download added to detached aria2 daemon.")

@cli.command()
def status():
    """Show the current download status."""
    try:
        # Launch aria2p TUI (top-like interface)
        subprocess.run(["aria2p"])
    except FileNotFoundError:
        click.echo("Error: aria2p is not installed.")

@cli.command()
def organize():
    """Manually organize completed downloads."""
    config = load_config()
    dl_path = config["download_path"]
    media_path = config["media_path"]
    
    click.echo("Organizing downloads...")
    organize_downloads(dl_path, media_path)
    click.echo("Done.")

@cli.command()
@click.argument('gid')
@click.argument('num_files')
@click.argument('path')
def hook(gid, num_files, path):
    """Hidden command called by aria2c on download complete."""
    config = load_config()
    media_path = config["media_path"]
    dl_path = config["download_path"]
    
    # aria2c passes 0 for num_files if the download is a single file, actually the docs say it passes the number of files.
    # If the download has no files, we do nothing.
    if num_files == "0":
        return
        
    from pathlib import Path
    from .organizer import process_item, move_to_trash
    
    item_path = Path(path)
    dl_dir = Path(dl_path)
    
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

if __name__ == '__main__':
    cli()
