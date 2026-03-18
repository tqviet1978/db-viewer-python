"""App-level configuration and data file helpers."""

import json
import os
from pathlib import Path

VERSION = "1.0.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9876
DATA_DIR = str(Path.home() / ".dbviewer" / "data")


def ensure_data_dir(data_dir: str = DATA_DIR) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)


def load_json(filepath: str | Path) -> list | dict:
    """Load a JSON file, returning empty list if missing."""
    path = Path(filepath)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_json(filepath: str | Path, data: list | dict) -> None:
    """Save data to a JSON file, creating parent dirs as needed."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_connections(data_dir: str = DATA_DIR) -> list[dict]:
    """Load connections from connections.json."""
    return load_json(Path(data_dir) / "connections.json")


def get_config(data_dir: str = DATA_DIR) -> dict:
    """Load optional app config from config.json."""
    result = load_json(Path(data_dir) / "config.json")
    if isinstance(result, dict):
        return result
    return {}


def get_ai_config(data_dir: str = DATA_DIR) -> dict:
    """
    Return AI configuration merging config.json with environment variables.
    Returns empty dict if no AI is configured.
    """
    cfg = get_config(data_dir)
    ai_cfg = {
        "provider": os.environ.get("DBVIEWER_AI_PROVIDER", cfg.get("ai_provider", "")),
        "api_key": os.environ.get("DBVIEWER_AI_API_KEY", cfg.get("ai_api_key", "")),
        "model": os.environ.get("DBVIEWER_AI_MODEL", cfg.get("ai_model", "gpt-4-turbo")),
        "org_id": cfg.get("ai_org_id", ""),
    }
    return ai_cfg
