import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    'token': '',
    'bot': {
        'prefix': '!',
        'version': '1.2.3',
        'activity_type': 'watching',
        'activity_text': 'your commands',
        'status': 'online',
    },
    'features': {
        'logging': True,
    },
    'roster': {
        'roles': [],
        'include_members': [],
        'exclude_members': [],
        'display_channel': None,
        'roster_message_id': None,
        'promotion_channel': None,
        'welcome_channel': None,
        'welcome_canvas': None,
        'name': 'Royal Family Roster',
    },
    'logging_channels': {
        'chat_channel': None,
        'server_channel': None,
        'leave_ping_role': None,
    },
}


def _merge_defaults(current: Any, defaults: Any) -> Any:
    if isinstance(defaults, dict):
        merged = {}
        current = current if isinstance(current, dict) else {}
        for key, default_value in defaults.items():
            merged[key] = _merge_defaults(current.get(key), default_value)
        for key, value in current.items():
            if key not in merged:
                merged[key] = value
        return merged

    if current is None:
        return deepcopy(defaults)

    return current


def load_config(config_path: Path) -> dict[str, Any]:
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        try:
            with config_path.open('r', encoding='utf-8') as config_file:
                loaded = json.load(config_file)
        except (OSError, json.JSONDecodeError):
            loaded = {}
    else:
        loaded = {}

    merged = _merge_defaults(loaded, DEFAULT_CONFIG)

    if not config_path.exists() or merged != loaded:
        save_config(config_path, merged)

    return merged


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open('w', encoding='utf-8') as config_file:
        json.dump(config, config_file, indent=2)