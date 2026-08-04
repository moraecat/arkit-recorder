from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    listen_port: int = 49983
    forward_host: str = "127.0.0.1"
    forward_port: int = 49984
    clips_dir: str = "clips"
    crossfade_live_ms: int = 300
    crossfade_loop_ms: int = 500


def load_config(path: Path) -> Config:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Config)}
        return Config(**{k: v for k, v in data.items() if k in known})
    config = Config()
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return config


def save_config(path: Path, config: Config) -> None:
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
