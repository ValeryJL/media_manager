import os
import re
import shutil
import logging
from pathlib import Path
from guessit import guessit

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v"}
SUB_EXTENSIONS = {".srt", ".sub", ".ass", ".vtt"}

# Regex to strip trailing SxxE / Sxx / Exx tokens that guessit sometimes leaves in titles
_SE_TRAIL_RE = re.compile(r'\s+[Ss]\d+[Ee]?\d*$|\s+[Ee]\d+$', re.IGNORECASE)

def sanitize_title(title: str) -> str:
    """Remove stray S01E-style fragments from a guessit-parsed title."""
    if not title:
        return title
    return _SE_TRAIL_RE.sub('', title).strip()

def is_downloading(path: Path) -> bool:
    """
    Check if the path or any of its contents are still being downloaded by aria2.
    A '.aria2' control file indicates the download is incomplete.
    """
    # 1. If the path itself is a .aria2 control file
    if path.suffix == ".aria2":
        return True

    # 2. Check for a sibling .aria2 control file (e.g., 'file.mkv.aria2' or 'Folder.aria2')
    # This is the standard way aria2c marks active downloads.
    if Path(str(path) + ".aria2").exists():
        return True

    # 3. If it's a directory, also scan inside it for any .aria2 files
    # (Sometimes aria2c puts control files inside if the structure is complex)
    if path.is_dir():
        for root, _, files in os.walk(path):
            if any(f.endswith(".aria2") for f in files):
                return True
    return False

def organize_downloads(download_path: str, media_path: str):
    """Scan download folder and move completed files to correct media destinations."""
    dl_dir = Path(download_path)
    media_dir = Path(media_path)
    trash_dir = media_dir / ".trash"

    if not dl_dir.exists():
        logger.error(f"Download path {dl_dir} does not exist.")
        return

    for item in dl_dir.iterdir():
        # Skip hidden files (.aria2 control files etc.)
        if item.name.startswith("."):
            continue
        if is_downloading(item):
            logger.info(f"Skipping {item.name}: still downloading (.aria2 found).")
            continue

        logger.info(f"Processing {item.name}...")
        process_item(item, media_dir, trash_dir)

def safe_move(src: Path, dest_dir: Path) -> bool:
    """
    Moves src into dest_dir. If a file with the same name already exists
    at the destination, skip it (do NOT overwrite).
    Returns True if moved, False if skipped.
    """
    dest = dest_dir / src.name
    if dest.exists():
        logger.info(f"Skipping {src.name}: already exists at {dest_dir}")
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    logger.info(f"Moved {src.name} -> {dest_dir}")
    return True

def process_item(item: Path, media_dir: Path, trash_dir: Path):
    """Process a single completed file or directory from the downloads folder."""
    # Safety: never process something that is still downloading
    if is_downloading(item):
        logger.warning(f"Aborting process of {item.name}: .aria2 control file found.")
        return

    files_to_process = []

    if item.is_file():
        files_to_process.append(item)
    else:
        for root, _, files in os.walk(item):
            for file in files:
                fpath = Path(root) / file
                # Skip control files entirely
                if fpath.suffix == ".aria2":
                    continue
                # Skip any file that is still downloading
                if is_downloading(fpath):
                    logger.info(f"Skipping {fpath.name}: still downloading.")
                    continue
                files_to_process.append(fpath)

    media_files = [f for f in files_to_process if f.suffix.lower() in MEDIA_EXTENSIONS]
    sub_files   = [f for f in files_to_process if f.suffix.lower() in SUB_EXTENSIONS]
    other_files = [f for f in files_to_process if f not in media_files and f not in sub_files]

    if not media_files:
        logger.info(f"No media files found in {item.name}. Moving to trash.")
        move_to_trash(item, trash_dir)
        return

    for media_file in media_files:
        guess = guessit(media_file.name)

        if guess.get("type") == "episode":
            title  = sanitize_title(str(guess.get("title", "Unknown Series")).title())
            season = guess.get("season") or 1   # default to 1 if guessit can't detect
            dest_folder = media_dir / "Shows" / title / f"Season {season}"
        else:
            title  = str(guess.get("title", "Unknown Movie")).title()
            year   = guess.get("year", "")
            folder = f"{title} ({year})" if year else title
            dest_folder = media_dir / "Movies" / folder

        safe_move(media_file, dest_folder)

        # Move matching subtitles to the same destination
        for sub in list(sub_files):
            safe_move(sub, dest_folder)
            sub_files.remove(sub)

    # Move remaining other files to trash (empty dirs, NFOs, etc.)
    for other in other_files:
        move_to_trash(other, trash_dir)

    # If the original download was a directory, try to clean it up
    if item.is_dir():
        # Remove empty subdirs
        try:
            # Only remove if now empty (all media was moved out)
            remaining = list(item.rglob("*"))
            remaining = [f for f in remaining if not f.name.endswith(".aria2")]
            if not remaining:
                shutil.rmtree(str(item))
                logger.info(f"Removed empty source directory: {item}")
            else:
                # Still has stuff — move the remnants to trash
                move_to_trash(item, trash_dir)
        except Exception as e:
            logger.warning(f"Could not clean up {item}: {e}")

def move_to_trash(item: Path, trash_dir: Path):
    """Move a file or folder to the trash directory. Never overwrites existing trash items."""
    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / item.name
    # Avoid collision with existing trash items by appending a suffix
    if dest.exists():
        base = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = trash_dir / f"{base}_{counter}{suffix}"
            counter += 1
    try:
        shutil.move(str(item), str(dest))
        logger.info(f"Trashed: {item.name} -> {dest}")
    except Exception as e:
        logger.error(f"Failed to move {item} to trash: {e}")
