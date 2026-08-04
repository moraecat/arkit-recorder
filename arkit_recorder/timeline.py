from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import Frame, parse_packet


@dataclass
class TimelineData:
    frames: list[tuple[int, str]] = field(default_factory=list)
    duration_ms: int = 0


def load_timeline(path: Path) -> TimelineData:
    frames: list[tuple[int, str]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                frames.append((int(entry["t"]), str(entry["d"])))
            except (ValueError, KeyError, TypeError):
                continue  # 손상 라인 스킵 (ClipPlayer.load와 동일 규칙)
    duration = frames[-1][0] if frames else 0
    return TimelineData(frames=frames, duration_ms=duration)


def frame_activity(prev: Frame | None, curr: Frame | None) -> float:
    # 두 프레임 모두에 있는 키만 합산. trackingStatus 제외.
    if prev is None or curr is None:
        return 0.0
    total = 0.0
    for name, value in curr.blendshapes.items():
        if name == "trackingStatus":
            continue
        prev_value = prev.blendshapes.get(name)
        if prev_value is not None:
            total += abs(value - prev_value)
    return total


def activity_curve(data: TimelineData) -> list[tuple[int, float]]:
    curve: list[tuple[int, float]] = []
    prev: Frame | None = None
    for t_ms, packet in data.frames:
        frame = parse_packet(packet)
        if frame is None:
            curve.append((t_ms, 0.0))
            continue  # prev는 마지막 유효 프레임 유지
        curve.append((t_ms, frame_activity(prev, frame)))
        prev = frame
    return curve


# 값 타입 int는 protocol.parse_packet이 정수로 파싱함을 전제로 한다
def blendshape_curve(data: TimelineData, name: str) -> list[tuple[int, int]]:
    curve: list[tuple[int, int]] = []
    for t_ms, packet in data.frames:
        frame = parse_packet(packet)
        if frame is None:
            continue
        value = frame.blendshapes.get(name)
        if value is not None:
            curve.append((t_ms, value))
    return curve


def blendshape_names(data: TimelineData) -> list[str]:
    names: set[str] = set()
    for _, packet in data.frames:
        frame = parse_packet(packet)
        if frame is not None:
            names.update(frame.blendshapes)
    names.discard("trackingStatus")
    return sorted(names)


def frame_index_at(data: TimelineData, t_ms: int) -> int:
    if not data.frames:
        return -1
    times = [t for t, _ in data.frames]
    index = bisect_right(times, t_ms) - 1
    return max(0, index)


def trim(data: TimelineData, start_ms: int, end_ms: int) -> list[tuple[int, str]]:
    selected = [(t, p) for t, p in data.frames if start_ms <= t <= end_ms]
    if not selected:
        return []
    base = selected[0][0]
    return [(t - base, p) for t, p in selected]


def save_frames(frames: list[tuple[int, str]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for t_ms, packet in frames:
            f.write(json.dumps({"t": t_ms, "d": packet}) + "\n")
    return len(frames)
