import os
import sys
from pathlib import Path
import yaml


def get_public_dir() -> Path:
    """Return the shared public user directory for the current OS."""
    if os.name == "nt":
        return Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    if sys.platform == "darwin":
        return Path("/Users/Shared")
    return Path("/srv/public")


def get_base_dir() -> Path:
    """
    Determine the base directory for Media Manager (either the Public user folder
    for all-users installations or Path.home() for single-user installations).
    """
    env_home = os.environ.get("MEDIA_MANAGER_HOME")
    if env_home:
        return Path(env_home)

    public_dir = get_public_dir()

    # 1. If running from a Python interpreter located inside the Public directory, use Public
    try:
        exe_path = Path(os.path.normcase(os.path.abspath(sys.executable)))
        pub_path = Path(os.path.normcase(os.path.abspath(str(public_dir))))
        if exe_path.is_relative_to(pub_path):
            return public_dir
    except Exception:
        pass

    # 2. If user-specific config exists, prefer user home
    user_config = Path.home() / ".config" / "media_manager" / "config.yml"
    if user_config.exists():
        return Path.home()

    # 3. If public config exists, use Public directory
    public_config = public_dir / ".config" / "media_manager" / "config.yml"
    if public_config.exists():
        return public_dir

    return Path.home()


DEFAULT_MEDIA_DIR = get_base_dir() / "Media"

DEFAULT_CONFIG = {
    "download_path": str(DEFAULT_MEDIA_DIR / "Downloads"),
    "media_path": str(DEFAULT_MEDIA_DIR),
}


def get_config_dir() -> Path:
    config_dir = get_base_dir() / ".config" / "media_manager"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_config(config_path: str = None) -> dict:
    if not config_path:
        path = get_config_dir() / "config.yml"
    else:
        path = Path(config_path)

    base_dir = get_base_dir()
    default_media_dir = base_dir / "Media"
    default_config = {
        "download_path": str(default_media_dir / "Downloads"),
        "media_path": str(default_media_dir),
    }

    if not path.exists():
        # Ensure default Media directories exist
        (default_media_dir / "Downloads").mkdir(parents=True, exist_ok=True)
        default_media_dir.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, default_flow_style=False)
        return default_config.copy()

    with open(path, "r", encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}

    # Merge with defaults
    config = default_config.copy()
    config.update(user_config)

    # Expand vars like $HOME, ~, $PUBLIC and %USERPROFILE% / %PUBLIC% for path keys
    public_dir = get_public_dir()
    for k in ("download_path", "media_path"):
        v = config.get(k)
        if isinstance(v, str):
            expanded = v
            if "$PUBLIC" in expanded:
                expanded = expanded.replace("$PUBLIC", str(public_dir))
            if "$HOME" in expanded:
                expanded = expanded.replace("$HOME", str(base_dir))
            expanded = os.path.expanduser(expanded)
            expanded = os.path.expandvars(expanded)
            config[k] = str(Path(expanded).resolve())

    # Ensure directories exist
    try:
        Path(config["download_path"]).mkdir(parents=True, exist_ok=True)
        Path(config["media_path"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    return config
