# arkit_recorder/clips.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TAIL_BYTES = 4096  # 길이 계산 시 파일 끝에서 읽는 최대 바이트


@dataclass
class ClipInfo:
    name: str
    path: Path
    duration_s: float | None
    size_bytes: int


def _read_duration(path: Path) -> float | None:
    # t는 단조증가이므로 마지막 유효 라인의 t가 총 길이. 꼬리만 읽는다.
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            return int(entry["t"]) / 1000.0
        except (ValueError, KeyError, TypeError):
            return None  # 마지막 유효 라인이 손상
    return None  # 빈 파일


def list_clips(clips_dir: Path) -> list[ClipInfo]:
    if not clips_dir.exists():
        return []
    infos = []
    for path in sorted(clips_dir.glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        infos.append(
            ClipInfo(
                name=path.stem,
                path=path,
                duration_s=_read_duration(path),
                size_bytes=path.stat().st_size,
            )
        )
    return infos


def rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("클립 이름이 비어 있습니다")
    if new_name.startswith("_"):
        raise ValueError("밑줄로 시작하는 이름은 사용할 수 없습니다")
    old_path = clips_dir / (old_name + ".jsonl")
    new_path = clips_dir / (new_name + ".jsonl")
    if not old_path.exists():
        raise ValueError(f"클립을 찾을 수 없습니다: {old_name}")
    if new_path.exists():
        raise ValueError(f"같은 이름의 클립이 이미 있습니다: {new_name}")
    old_path.rename(new_path)
    return new_path


def delete_clip(path: Path) -> None:
    path.unlink(missing_ok=True)
