import os
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "download_path": os.path.expandvars("$HOME/Media/Downloads"),
    "media_path": os.path.expandvars("$HOME/Media")
}

def load_config(config_path: str = None) -> dict:
    if not config_path:
        config_path = os.path.expanduser("~/.config/media_manager/config.yml")
    
    path = Path(config_path)
    if not path.exists():
        # Create default if doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(DEFAULT_CONFIG, f)
        return DEFAULT_CONFIG
        
    with open(path, "r") as f:
        user_config = yaml.safe_load(f) or {}
    
    # Merge with defaults
    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    
    # Expand vars like $HOME
    for k, v in config.items():
        if isinstance(v, str):
            config[k] = os.path.expandvars(os.path.expanduser(v))
            
    return config
