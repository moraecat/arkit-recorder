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
        self._range_start = 0
        self._range_end: int | None = None

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

    def set_range(self, start_ms: int, end_ms: int | None) -> None:
        # 재생 중 구간 변경 (GUI 단일 작성자, int 대입은 GIL 원자적)
        self._range_start = start_ms
        self._range_end = end_ms

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
        self._range_start = range_start_ms
        self._range_end = range_end_ms
        first_start = max(start_ms, range_start_ms)
        # 시작 경계만 선필터, 끝 경계는 매 프레임 동적 확인 (실시간 구간 반영)
        frames = (
            [(t, p) for t, p in self._frames if t >= first_start]
            if first_start > 0 else self._frames
        )
        if not self._has_playable(frames):
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            # base_ms 규칙: 바퀴 시작 경계가 0이면 base=0, 아니면 그 바퀴 첫 프레임 t
            base_ms = frames[0][0] if first_start > 0 else 0
            while not self._stop_event.is_set():
                start = self._now()
                for t_ms, packet in frames:
                    if self._stop_event.is_set():
                        return
                    end = self._range_end
                    if end is not None and t_ms > end:
                        break  # 현재 구간 끝 초과 — 바퀴 종료 (축소 즉시 반영)
                    rel_ms = t_ms - base_ms
                    delay = start + rel_ms / 1000.0 - self._now()
                    if delay > 0:
                        self._sleep(delay)
                    out = self._prepare(packet, rel_ms, fade_src, fade_ms)
                    if out is not None:
                        self._send(out)
                        self.last_sent_packet = out
                        self.position_ms = t_ms
                # 구간 끝 break 포함 모든 바퀴 종료가 여기로 온다 (비루프면 재생 종료)
                if not loop:
                    return
                # 되감기: 현재 구간 시작 기준 재계산 (실시간 반영)
                rewind_start = self._range_start
                frames = (
                    [(t, p) for t, p in self._frames if t >= rewind_start]
                    if rewind_start > 0 else self._frames
                )
                if not self._has_playable(frames):
                    return
                base_ms = frames[0][0] if rewind_start > 0 else 0
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False

    def _has_playable(self, frames: list[tuple[int, str]]) -> bool:
        # 시작 필터된 목록의 첫 프레임이 현재 구간 끝 이내인가
        # 판단 직후 set_range가 끼어들 수 있으나(GUI 단일 작성자) 첫 프레임의 동적 end 확인이 최종 방어
        if not frames:
            return False
        end = self._range_end
        return end is None or frames[0][0] <= end

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
