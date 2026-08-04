from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

from .protocol import Frame, parse_packet
from .timeline import frame_activity


class ClipRecorder:
    def __init__(self, tmp_path: Path, now=time.perf_counter):
        self._tmp_path = tmp_path
        self._now = now
        self._lock = threading.Lock()
        self._file = None
        self._start_time = 0.0
        self.frame_count = 0
        self._wave: deque[tuple[int, float]] = deque(maxlen=36000)  # 60fps 10분
        self._prev_frame: Frame | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._file is not None

    def start(self) -> None:
        with self._lock:
            if self._file is not None:
                return
            self._tmp_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._tmp_path, "w", encoding="utf-8")
            self._start_time = self._now()
            self.frame_count = 0
            self._wave.clear()
            self._prev_frame = None

    def feed(self, packet: str) -> None:
        with self._lock:
            if self._file is None:
                return
            t_ms = round((self._now() - self._start_time) * 1000)
            self._file.write(json.dumps({"t": t_ms, "d": packet}) + "\n")
            self.frame_count += 1
            frame = parse_packet(packet)
            if frame is None:
                self._wave.append((t_ms, 0.0))
            else:
                self._wave.append((t_ms, frame_activity(self._prev_frame, frame)))
                self._prev_frame = frame

    def stop_and_save(self, final_path: Path) -> int:
        with self._lock:
            if self._file is None:
                return 0
            self._file.close()
            self._file = None
            final_path.parent.mkdir(parents=True, exist_ok=True)
            self._tmp_path.replace(final_path)
            return self.frame_count

    def discard(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._tmp_path.unlink(missing_ok=True)

    def live_wave(self) -> list[tuple[int, float]]:
        with self._lock:
            return list(self._wave)
