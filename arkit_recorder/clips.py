# arkit_recorder/clips.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .i18n import tr

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
            # 역순 순회에서 첫 비어있지 않은 라인 = 실제 마지막 라인:
            #   (1) tail은 항상 파일 끝을 포함하므로 역순 첫 비어있지 않은 라인이 실제
            #       마지막 라인이다.
            #   (2) 4096바이트 경계에서 잘릴 수 있는 것은 tail의 "첫" 라인(가장 오래된
            #       라인)이며, 마지막 라인에 도달하기 전에 이미 유효한 t를 얻으므로
            #       경계 절단은 duration 계산에 영향을 주지 않는다.
            #   (3) 마지막 라인 자체가 손상된 경우(녹화 중 크래시 등)는 스펙에 따라
            #       None을 반환한다. 이전 라인으로 거슬러 올라가지 않는 것이 의도된
            #       동작이다 -- 부분 기록을 유효한 길이로 오인하지 않기 위함.
            return None
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


def validate_clip_name(clips_dir: Path, name: str) -> Path:
    name = name.strip()
    if not name:
        raise ValueError(tr("err.name_empty"))
    if name.startswith("_"):
        raise ValueError(tr("err.name_underscore"))
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(tr("err.name_pathchars"))
    path = clips_dir / (name + ".jsonl")
    if path.exists():
        raise ValueError(tr("err.name_taken", name=name))
    return path


def rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path:
    new_path = validate_clip_name(clips_dir, new_name)
    old_path = clips_dir / (old_name + ".jsonl")
    if not old_path.exists():
        raise ValueError(tr("err.clip_missing", name=old_name))
    old_path.rename(new_path)
    return new_path


def delete_clip(path: Path) -> None:
    path.unlink(missing_ok=True)
