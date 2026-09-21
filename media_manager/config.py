import os
from pathlib import Path
import yaml

DEFAULT_MEDIA_DIR = Path.home() / "Media"

DEFAULT_CONFIG = {
    "download_path": str(DEFAULT_MEDIA_DIR / "Downloads"),
    "media_path": str(DEFAULT_MEDIA_DIR)
}

def get_config_dir() -> Path:
    config_dir = Path.home() / ".config" / "media_manager"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def load_config(config_path: str = None) -> dict:
    if not config_path:
        path = get_config_dir() / "config.yml"
    else:
        path = Path(config_path)
    
    if not path.exists():
        # Ensure default Media directories exist
        (DEFAULT_MEDIA_DIR / "Downloads").mkdir(parents=True, exist_ok=True)
        DEFAULT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
        return DEFAULT_CONFIG.copy()
        
    with open(path, "r", encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}
    
    # Merge with defaults
    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    
    # Expand vars like $HOME, ~ and %USERPROFILE%
    for k, v in config.items():
        if isinstance(v, str):
            expanded = os.path.expanduser(v)
            if "$HOME" in expanded:
                expanded = expanded.replace("$HOME", str(Path.home()))
            expanded = os.path.expandvars(expanded)
            config[k] = str(Path(expanded).resolve())
            
    # Ensure directories exist
    try:
        Path(config["download_path"]).mkdir(parents=True, exist_ok=True)
        Path(config["media_path"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    return config

