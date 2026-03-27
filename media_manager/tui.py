import subprocess
import json
import questionary
from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()

def search_interactive(query_str: str) -> str:
    """Runs pirate-get in JSON mode, displays a rich table, and returns the chosen magnet link."""
    with console.status(f"[bold green]Searching for '{query_str}'..."):
        try:
            # -j for JSON output. We don't use -C here because we'll handle the output manually
            result = subprocess.run(
                ["pirate-get", query_str, "-j"],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            console.print("[bold red]Search failed or no results found.[/]")
            return None
        except FileNotFoundError:
            console.print("[bold red]Error: pirate-get is not installed or not in PATH.[/]")
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
        
    choices.append(questionary.Choice(title="❌ Cancel", value=None))

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

    return selected_magnet
