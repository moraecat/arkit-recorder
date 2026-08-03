from __future__ import annotations

import socket
import threading
import time
from collections import deque
from enum import Enum
from pathlib import Path

from .config import Config
from .player import ClipPlayer
from .protocol import Frame, blend_frames, parse_packet, serialize_frame
from .recorder import ClipRecorder

LIVE_TIMEOUT = 0.5  # Warudo와 같은 기준: 이 시간 수신 없으면 트래킹 끊김


class Mode(Enum):
    PASSTHROUGH = "passthrough"
    RECORDING = "recording"
    PLAYING = "playing"


class FaceProxy:
    def __init__(self, config: Config, base_dir: Path):
        self._config = config
        self.clips_dir = base_dir / config.clips_dir
        self._mode = Mode.PASSTHROUGH
        self._mode_lock = threading.Lock()
        self._recv_socket = None
        self._send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._forward_addr = (config.forward_host, config.forward_port)
        self._stop_event = threading.Event()
        self._recv_thread = None
        self._player_thread = None
        self._recorder = ClipRecorder(self.clips_dir / "_recording.tmp.jsonl")
        self._player: ClipPlayer | None = None
        # 수신 스레드만 쓰고 GUI 스레드가 읽음. CPython GIL 원자성에 의존.
        self._recv_times = deque(maxlen=120)
        self._last_recv_time: float | None = None
        self._last_live_packet: str | None = None
        self._fade_back_from: Frame | None = None
        self._fade_back_until = 0.0
        self.bind_error: str | None = None
        self.bound_port: int | None = None

    @property
    def mode(self) -> Mode:
        with self._mode_lock:
            return self._mode

    def start(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.bind(("0.0.0.0", self._config.listen_port))
        except OSError as e:
            self.bind_error = (
                f"포트 {self._config.listen_port} 바인드 실패 "
                f"(다른 프로그램이 사용 중일 수 있음): {e}"
            )
            self._send_socket.close()
            return
        self._recv_socket = sock
        self.bound_port = sock.getsockname()[1]
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.stop_playback()
        if self._recv_socket is not None:
            self._recv_socket.close()
        if self._recorder.is_recording:
            self._recorder.discard()
        self._send_socket.close()

    def receive_stats(self) -> tuple[int, float | None]:
        now = time.perf_counter()
        hz = sum(1 for t in self._recv_times if now - t <= 1.0)
        since = None if self._last_recv_time is None else now - self._last_recv_time
        return hz, since

    def live_available(self) -> bool:
        return (
            self._last_recv_time is not None
            and time.perf_counter() - self._last_recv_time <= LIVE_TIMEOUT
        )

    # -- 수신 스레드 ------------------------------------------

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, _ = self._recv_socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            packet = data.decode("ascii", errors="replace")
            now = time.perf_counter()
            # _last_recv_time을 먼저 갱신해 쓰기 순서 일관성 보장
            self._last_recv_time = now
            self._recv_times.append(now)
            self._last_live_packet = packet
            mode = self._mode  # GIL 원자 읽기 의존, 핫패스이므로 락 생략
            if mode is Mode.PLAYING:
                continue  # 재생 중엔 라이브 전달 차단 (수신 통계만 갱신)
            out = self._apply_fade_back(packet, now)
            self._forward(out)
            if mode is Mode.RECORDING:
                self._recorder.feed(packet)  # 페이드 보정 전 원본을 기록

    def _forward(self, packet: str) -> None:
        try:
            self._send_socket.sendto(
                packet.encode("ascii", errors="replace"), self._forward_addr
            )
        except OSError:
            pass

    def _apply_fade_back(self, packet: str, now: float) -> str:
        # 재생 종료 직후 crossfade_live_ms 동안 라이브로 부드럽게 복귀
        if self._fade_back_from is None or now >= self._fade_back_until:
            return packet
        live = parse_packet(packet)
        if live is None:
            return packet
        total = self._config.crossfade_live_ms / 1000.0
        t = 1.0 - (self._fade_back_until - now) / total
        return serialize_frame(blend_frames(self._fade_back_from, live, t))

    # -- 녹화 조작 (GUI 스레드에서 호출) ----------------------

    def start_recording(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return
            self._recorder.start()
            self._mode = Mode.RECORDING

    def stop_recording(self, name: str) -> Path:
        with self._mode_lock:
            path = self.clips_dir / (name + ".jsonl")
            self._recorder.stop_and_save(path)
            if self._mode is Mode.RECORDING:
                self._mode = Mode.PASSTHROUGH
            return path

    # -- 재생 조작 -------------------------------------------------

    def start_playback(self, clip_path: Path, loop: bool) -> int:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return 0
            player = ClipPlayer(
                send=self._forward,
                crossfade_live_ms=self._config.crossfade_live_ms,
                crossfade_loop_ms=self._config.crossfade_loop_ms,
            )
            count = player.load(clip_path)
            if count == 0:
                return 0
            lead_in = self._last_live_packet if self.live_available() else None
            self._player = player
            self._fade_back_from = None  # 이전 복귀 페이드 취소
            self._mode = Mode.PLAYING
        # join-less 설계: 참조는 최신 스레드만 유지, 이전 스레드는 stop()으로 스스로 종료됨
        self._player_thread = threading.Thread(
            target=self._run_player, args=(player, loop, lead_in), daemon=True
        )
        self._player_thread.start()
        return count

    def _run_player(self, player: ClipPlayer, loop: bool, lead_in: str | None) -> None:
        try:
            player.play(loop=loop, lead_in_packet=lead_in)
        finally:
            self._finish_playback(player)

    def _finish_playback(self, player: ClipPlayer) -> None:
        with self._mode_lock:
            if self._mode is Mode.PLAYING:
                self._mode = Mode.PASSTHROUGH
            if self.live_available() and player.last_sent_packet:
                frame = parse_packet(player.last_sent_packet)
                if frame is not None:
                    self._fade_back_from = frame
                    self._fade_back_until = (
                        time.perf_counter()
                        + self._config.crossfade_live_ms / 1000.0
                    )

    def stop_playback(self) -> None:
        player = self._player
        if player is not None:
            player.stop()
