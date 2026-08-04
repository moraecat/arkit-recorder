from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from .protocol import Frame, blend_frames, parse_packet, serialize_frame


class ClipPlayer:
    def __init__(
        self,
        send: Callable[[str], None],
        now=time.perf_counter,
        sleep=time.sleep,
        crossfade_live_ms: int = 300,
        crossfade_loop_ms: int = 500,
    ):
        self._send = send
        self._now = now
        self._sleep = sleep
        self._crossfade_live_ms = crossfade_live_ms
        self._crossfade_loop_ms = crossfade_loop_ms
        self._frames: list[tuple[int, str]] = []
        self._stop_event = threading.Event()
        self.is_playing = False
        self.last_sent_packet: str | None = None
        self.skipped_lines = 0
        self.position_ms = 0

    def load(self, path: Path) -> int:
        frames = []
        self.skipped_lines = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    frames.append((int(entry["t"]), str(entry["d"])))
                except (ValueError, KeyError, TypeError):
                    self.skipped_lines += 1
        self._frames = frames
        return len(frames)

    def play(
        self,
        loop: bool = False,
        lead_in_packet: str | None = None,
        start_ms: int = 0,
        range_start_ms: int = 0,
        range_end_ms: int | None = None,
    ) -> None:
        # 블로킹 — 호출자는 별도 스레드에서 실행한다
        if self.is_playing:
            return
        range_frames = [
            (t, p) for t, p in self._frames
            if t >= range_start_ms and (range_end_ms is None or t <= range_end_ms)
        ]
        first_start = max(start_ms, range_start_ms)
        first_frames = (
            [(t, p) for t, p in range_frames if t >= first_start]
            if first_start > 0 else range_frames
        )
        if not first_frames:
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            frames = first_frames
            # base_ms 규칙: 바퀴 시작 경계가 0이면 0, 아니면 그 바퀴 첫 프레임 t
            base_ms = first_frames[0][0] if first_start > 0 else 0
            while not self._stop_event.is_set():
                start = self._now()
                for t_ms, packet in frames:
                    if self._stop_event.is_set():
                        return
                    rel_ms = t_ms - base_ms
                    delay = start + rel_ms / 1000.0 - self._now()
                    if delay > 0:
                        self._sleep(delay)
                    out = self._prepare(packet, rel_ms, fade_src, fade_ms)
                    if out is not None:
                        self._send(out)
                        self.last_sent_packet = out
                        self.position_ms = t_ms
                if not loop:
                    return
                # 루프 되감기는 재생 구간 시작부터 (구간 미지정 시 0 = 기존 동작)
                frames = range_frames
                base_ms = range_frames[0][0] if range_start_ms > 0 else 0
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False

    def _prepare(
        self, packet: str, t_ms: int, fade_src: Frame | None, fade_ms: int
    ) -> str | None:
        frame = parse_packet(packet)
        if frame is None:
            return packet  # 파싱 불가: 원본 그대로, 블렌딩만 생략
        if frame.blendshapes.get("trackingStatus") == 0:
            return None  # Warudo가 무시하는 프레임: 송출 생략
        if fade_src is not None and fade_ms > 0 and t_ms < fade_ms:
            t = t_ms / fade_ms
            return serialize_frame(blend_frames(fade_src, frame, t))
        return packet

    def stop(self) -> None:
        self._stop_event.set()
