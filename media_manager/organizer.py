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

# Windows invalid path characters: < > : " / \ | ? *
_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')

def extract_single_value(val, default=None):
    if isinstance(val, (list, tuple)):
        return val[0] if val else default
    return val if val is not None else default

def clean_filename(name: str) -> str:
    """Sanitize names for Windows and Unix filesystem safety."""
    if not name:
        return ""
    # Replace colon with hyphen-space (e.g. "Mission: Impossible" -> "Mission - Impossible")
    cleaned = str(name).replace(":", " - ")
    # Replace other invalid characters with empty string
    cleaned = _INVALID_CHARS_RE.sub("", cleaned)
    # Remove trailing dots and spaces (forbidden on Windows directory/file names)
    cleaned = cleaned.strip(". ")
    # Replace multiple spaces with single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned

def sanitize_title(title) -> str:
    """Remove stray S01E-style fragments and invalid filesystem chars from a title."""
    if not title:
        return ""
    if isinstance(title, (list, tuple)):
        title = title[0]
    title_str = str(title).strip()
    title_str = _SE_TRAIL_RE.sub('', title_str).strip()
    return clean_filename(title_str)


# Regex to match Season directories (Season 1, Temporada 2, S03, etc.)
SEASON_DIR_RE = re.compile(r'^(?:Season|Series|Temporada|Stagione|Staffel|S|T)\s*(\d+)$', re.IGNORECASE)

# Regex to match Extras / Specials directories
EXTRAS_DIR_RE = re.compile(
    r'^(?:Extras?|Extra\s*Episod(?:e|es|s)?|Specials?|Shorts?|Featurettes?|Bonus|Season\s*0+|S0+)$',
    re.IGNORECASE
)

def extract_season_from_path(media_file: Path, base_dir: Path):
    """Scan parent directories up to base_dir to find an explicit Season or Extras folder."""
    curr = media_file.parent
    while curr != base_dir and curr != curr.parent:
        name = curr.name
        m = SEASON_DIR_RE.match(name)
        if m:
            return int(m.group(1))
        if EXTRAS_DIR_RE.match(name):
            return 0
        curr = curr.parent
    return None

def find_effective_series_dir(media_file: Path, item: Path) -> Path:
    """
    For torrents containing multiple shows or franchises, locate the specific
    series folder containing the media file rather than using the torrent root.
    """
    if media_file == item or media_file.parent == item:
        return item
    if item.exists() and not item.is_dir():
        return item
    try:
        rel_dirs = media_file.parent.relative_to(item).parts
    except ValueError:
        return item
    if not rel_dirs:
        return item
    # If the first directory is a season or extras folder, the item itself is the series
    if SEASON_DIR_RE.match(rel_dirs[0]) or EXTRAS_DIR_RE.match(rel_dirs[0]):
        return item
    # Otherwise, rel_dirs[0] is an inner series folder (e.g. 'Ben 10 Alien Force')
    return item / rel_dirs[0]

def guess_media_info(media_file: Path, item: Path) -> dict:
    """
    Use guessit to parse media file information, leveraging directory context
    when available so episode titles are not mistaken for series titles.
    """
    effective_item = find_effective_series_dir(media_file, item)
    is_multi_pack = (effective_item != item)

    try:
        rel_path = media_file.relative_to(effective_item.parent)
    except ValueError:
        rel_path = media_file

    guess = dict(guessit(str(rel_path)))
    name_guess = dict(guessit(media_file.name))
    path_season = extract_season_from_path(media_file, item)

    # In multi-packs, the subfolder name (e.g. "Ben 10 Alien Force") is the series title.
    if is_multi_pack:
        # Use type=movie to prevent numbers in the show title (like '10') from being treated as episodes
        sub_guess = guessit(effective_item.name, {"type": "movie"})
        guess["title"] = sub_guess.get("title") or effective_item.name
        if name_guess.get("type") == "episode" or path_season is not None or guess.get("type") == "episode":
            guess["type"] = "episode"
    else:
        # If the relative path didn't detect an episode, but the filename clearly is an episode:
        if guess.get("type") != "episode" and name_guess.get("type") == "episode":
            series_title = guess.get("title")
            guess.update(name_guess)
            if series_title:
                guess["title"] = series_title

        # If title is still missing and item is a directory, try getting title from item directory name
        if not guess.get("title") and item.is_dir():
            dir_guess = guessit(effective_item.name, {"type": "movie"})
            if dir_guess.get("title"):
                guess["title"] = dir_guess.get("title")

    # For episodes, determine season and episode with strict directory precedence for seasons
    if guess.get("type") == "episode" or name_guess.get("type") == "episode" or path_season is not None:
        guess["type"] = "episode"
        if path_season is not None:
            guess["season"] = path_season
        else:
            name_season = name_guess.get("season")
            if name_season is not None and not isinstance(name_season, (list, tuple)):
                guess["season"] = name_season
            elif not guess.get("season") or isinstance(guess.get("season"), (list, tuple)):
                guess["season"] = 1

        name_ep = name_guess.get("episode")
        if name_ep is not None and not isinstance(name_ep, (list, tuple)):
            guess["episode"] = name_ep

    return guess

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

def organize_downloads(download_path: str, media_path: str, quiet: bool = False) -> list:
    """Scan download folder and move completed files to correct media destinations."""
    if not quiet and not logger.handlers and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    dl_dir = Path(download_path)
    media_dir = Path(media_path)
    trash_dir = media_dir / ".trash"
    report = []

    if not dl_dir.exists():
        if not quiet:
            logger.error(f"Download path {dl_dir} does not exist.")
        return report

    for item in dl_dir.iterdir():
        # Skip hidden files (.aria2 control files etc.)
        if item.name.startswith(".") or item.suffix == ".aria2":
            continue
        if is_downloading(item):
            if not quiet:
                logger.info(f"Skipping {item.name}: still downloading (.aria2 found).")
            report.append({
                "name": item.name,
                "kind": "downloading",
                "target": "-",
                "status": "downloading",
            })
            continue

        if not quiet:
            logger.info(f"Processing {item.name}...")
        item_events = process_item(item, media_dir, trash_dir)
        if item_events:
            report.extend(item_events)

    return report

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
    try:
        shutil.move(str(src), str(dest))
        logger.info(f"Moved {src.name} -> {dest_dir}")
        return True
    except PermissionError:
        logger.warning(f"Skipping {src.name}: file is locked or currently in use.")
        return False

def _rel_dest_str(dest_dir: Path, media_dir: Path) -> str:
    try:
        return str(dest_dir.resolve().relative_to(media_dir.resolve()))
    except Exception:
        return str(dest_dir)

def process_item(item: Path, media_dir: Path, trash_dir: Path) -> list:
    """Process a single completed file or directory from the downloads folder."""
    events = []
    # Safety: never process something that is still downloading
    if is_downloading(item):
        logger.warning(f"Aborting process of {item.name}: .aria2 control file found.")
        events.append({
            "name": item.name,
            "kind": "downloading",
            "target": "-",
            "status": "downloading",
        })
        return events

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
        events.append({
            "name": item.name,
            "kind": "trash",
            "target": ".trash",
            "status": "trashed",
        })
        return events

    for media_file in media_files:
        guess = guess_media_info(media_file, item)
        is_ep = guess.get("type") == "episode"

        if is_ep:
            raw_title = extract_single_value(guess.get("title"), "Unknown Series")
            title = sanitize_title(raw_title).title() or "Unknown Series"
            title = clean_filename(title)
            raw_season = extract_single_value(guess.get("season"), 1)
            try:
                season = int(raw_season)
            except (ValueError, TypeError):
                season = 1
            dest_folder = media_dir / "Shows" / title / f"Season {season}"
        else:
            raw_title = extract_single_value(guess.get("title"), "Unknown Movie")
            title = sanitize_title(raw_title).title() or "Unknown Movie"
            title = clean_filename(title)
            raw_year = extract_single_value(guess.get("year"), "")
            year = str(raw_year).strip() if raw_year else ""
            folder = f"{title} ({year})" if year else title
            folder = clean_filename(folder)
            dest_folder = media_dir / "Movies" / folder

        moved = safe_move(media_file, dest_folder)
        events.append({
            "name": media_file.name,
            "kind": "episode" if is_ep else "movie",
            "target": _rel_dest_str(dest_folder, media_dir),
            "status": "moved" if moved else "skipped",
        })

        # Move matching subtitles to the same destination
        media_stem = media_file.stem.lower()
        for sub in list(sub_files):
            sub_stem = sub.stem.lower()
            sub_info = guess_media_info(sub, item)
            matched = False
            if sub_stem == media_stem or sub_stem.startswith(media_stem + ".") or sub_stem.startswith(media_stem + "-"):
                matched = True
            elif (guess.get("type") == "episode" and
                  sub_info.get("season") == guess.get("season") and
                  sub_info.get("episode") == guess.get("episode")):
                matched = True

            if matched:
                sub_moved = safe_move(sub, dest_folder)
                events.append({
                    "name": sub.name,
                    "kind": "subtitle",
                    "target": _rel_dest_str(dest_folder, media_dir),
                    "status": "moved" if sub_moved else "skipped",
                })
                sub_files.remove(sub)

    # Move any remaining subtitles to their guessed destinations
    for sub in list(sub_files):
        sub_info = guess_media_info(sub, item)
        if sub_info.get("type") == "episode":
            sub_title = sanitize_title(extract_single_value(sub_info.get("title"), "Unknown Series")).title() or "Unknown Series"
            sub_title = clean_filename(sub_title)
            sub_season = extract_single_value(sub_info.get("season"), 1)
            try:
                sub_season = int(sub_season)
            except (ValueError, TypeError):
                sub_season = 1
            sub_dest = media_dir / "Shows" / sub_title / f"Season {sub_season}"
        else:
            sub_title = sanitize_title(extract_single_value(sub_info.get("title"), "Unknown Movie")).title() or "Unknown Movie"
            sub_title = clean_filename(sub_title)
            sub_year = extract_single_value(sub_info.get("year"), "")
            sub_year = str(sub_year).strip() if sub_year else ""
            sub_folder = f"{sub_title} ({sub_year})" if sub_year else sub_title
            sub_folder = clean_filename(sub_folder)
            sub_dest = media_dir / "Movies" / sub_folder
        sub_moved = safe_move(sub, sub_dest)
        events.append({
            "name": sub.name,
            "kind": "subtitle",
            "target": _rel_dest_str(sub_dest, media_dir),
            "status": "moved" if sub_moved else "skipped",
        })
        sub_files.remove(sub)

    # Move remaining other files to trash (empty dirs, NFOs, etc.)
    for other in other_files:
        move_to_trash(other, trash_dir)
        events.append({
            "name": other.name,
            "kind": "trash",
            "target": ".trash",
            "status": "trashed",
        })

    # If the original download was a directory, try to clean it up
    if item.is_dir():
        try:
            # Check if any actual files remain (excluding .aria2)
            remaining_files = [f for f in item.rglob("*") if f.is_file() and not f.name.endswith(".aria2")]
            if not remaining_files:
                shutil.rmtree(str(item))
                logger.info(f"Removed empty source directory: {item}")
            else:
                # Still has files — move the remnants to trash
                move_to_trash(item, trash_dir)
        except Exception as e:
            logger.warning(f"Could not clean up {item}: {e}")

    return events

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
    except PermissionError:
        logger.warning(f"Could not move {item} to trash: file is locked or in use.")
    except Exception as e:
        logger.error(f"Failed to move {item} to trash: {e}")
