from __future__ import annotations

import socket
import threading
import time
from collections import deque
from enum import Enum
from pathlib import Path

from .config import Config
from .i18n import tr
from .player import ClipPlayer
from .protocol import Frame, blend_frames, parse_packet, serialize_frame
from .recorder import ClipRecorder

LIVE_TIMEOUT = 0.5  # Warudo와 같은 기준: 이 시간 수신 없으면 트래킹 끊김


class Mode(Enum):
    PASSTHROUGH = "passthrough"
    RECORDING = "recording"
    PLAYING = "playing"
    SCRUBBING = "scrubbing"


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
        self._last_scrub_packet: str | None = None
        self.bind_error: str | None = None
        self.bound_port: int | None = None
        self._recv_stop = threading.Event()  # 리스너 전용 정지 (재시작 시 교체됨)

    @property
    def mode(self) -> Mode:
        with self._mode_lock:
            return self._mode

    def start(self) -> None:
        self._start_listener(self._config.listen_port)

    def stop(self) -> None:
        self._stop_event.set()
        self.stop_playback()
        self._stop_listener()
        if self._recorder.is_recording:
            self._recorder.discard()
        self._send_socket.close()

    def _start_listener(self, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.bind(("0.0.0.0", port))
        except OSError as e:
            self.bind_error = tr("err.bind_failed", port=port, error=e)
            return False
        self.bind_error = None
        self._recv_socket = sock
        self.bound_port = sock.getsockname()[1]
        self._recv_stop = threading.Event()
        self._recv_thread = threading.Thread(
            target=self._recv_loop, args=(sock, self._recv_stop), daemon=True
        )
        self._recv_thread.start()
        return True

    def _stop_listener(self) -> None:
        event = self._recv_stop  # 재시작 경합 대비: 로컬로 캡처 후 set
        event.set()
        if self._recv_socket is not None:
            self._recv_socket.close()
            self._recv_socket = None
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=2.0)
            self._recv_thread = None

    def receive_stats(self) -> tuple[int, float | None]:
        now = time.perf_counter()
        hz = sum(1 for t in self._recv_times if now - t <= 1.0)
        since = None if self._last_recv_time is None else now - self._last_recv_time
        return hz, since

    def live_wave(self) -> list[tuple[int, float]]:
        return self._recorder.live_wave()

    def live_available(self) -> bool:
        return (
            self._last_recv_time is not None
            and time.perf_counter() - self._last_recv_time <= LIVE_TIMEOUT
        )

    # -- 수신 스레드 ------------------------------------------

    def _recv_loop(self, sock: socket.socket, stop: threading.Event) -> None:
        while not (stop.is_set() or self._stop_event.is_set()):
            try:
                data, _ = sock.recvfrom(65535)
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
            if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
                continue  # 재생/스크럽 중엔 라이브 전달 차단 (수신 통계만 갱신)
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

    def finish_recording(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.RECORDING:
                return
            self._recorder.finish()
            self._mode = Mode.PASSTHROUGH

    def save_recording(self, name: str) -> Path:
        # finish_recording 직후 호출 전제(tmp 존재 보장) — save_to가 0을 반환하는
        # 경로(tmp 부재)는 이 흐름에서 발생하지 않으므로 반환값은 확인하지 않음
        path = self.clips_dir / (name + ".jsonl")
        self._recorder.save_to(path)
        return path

    def discard_recording(self) -> None:
        self._recorder.discard()

    def stop_recording(self, name: str) -> Path:
        self.finish_recording()
        return self.save_recording(name)

    # -- 재생 조작 -------------------------------------------------

    def start_playback(
        self,
        clip_path: Path,
        loop: bool,
        start_ms: int = 0,
        range_start_ms: int = 0,
        range_end_ms: int | None = None,
    ) -> int:
        with self._mode_lock:
            if self._mode not in (Mode.PASSTHROUGH, Mode.SCRUBBING):
                return 0
            from_scrub = self._mode is Mode.SCRUBBING
            player = ClipPlayer(
                send=self._forward,
                crossfade_live_ms=self._config.crossfade_live_ms,
                crossfade_loop_ms=self._config.crossfade_loop_ms,
            )
            count = player.load(clip_path)
            if count == 0:
                return 0
            if from_scrub:
                # 일시정지 재개: 고정 표정 -> 재생 첫 프레임 크로스페이드
                lead_in = self._last_scrub_packet
            else:
                lead_in = self._last_live_packet if self.live_available() else None
            self._player = player
            self._fade_back_from = None  # 이전 복귀 페이드 취소
            self._mode = Mode.PLAYING
        # join-less 설계: 참조는 최신 스레드만 유지, 이전 스레드는 stop()으로 스스로 종료됨
        self._player_thread = threading.Thread(
            target=self._run_player,
            args=(player, loop, lead_in, start_ms, range_start_ms, range_end_ms),
            daemon=True,
        )
        self._player_thread.start()
        return count

    def _run_player(
        self,
        player: ClipPlayer,
        loop: bool,
        lead_in: str | None,
        start_ms: int,
        range_start_ms: int,
        range_end_ms: int | None,
    ) -> None:
        try:
            player.play(
                loop=loop, lead_in_packet=lead_in, start_ms=start_ms,
                range_start_ms=range_start_ms, range_end_ms=range_end_ms,
            )
        finally:
            self._finish_playback(player)

    def playback_position_ms(self) -> int | None:
        # SCRUBBING은 의도적으로 None — 스크럽 중 플레이헤드는 위젯이 직접 관리
        with self._mode_lock:
            if self._mode is not Mode.PLAYING:
                return None
            player = self._player
        if player is None:
            return None
        return player.position_ms

    def update_playback_range(self, start_ms: int, end_ms: int | None) -> None:
        with self._mode_lock:
            if self._mode is not Mode.PLAYING:
                return
            player = self._player
        if player is not None:
            player.set_range(start_ms, end_ms)

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

    # -- 스크럽 (GUI 스레드에서 호출) --------------------------

    def begin_scrub(self) -> bool:
        player = None
        thread = None
        with self._mode_lock:
            if self._mode is Mode.PLAYING:
                player = self._player
                thread = self._player_thread
            elif self._mode is not Mode.PASSTHROUGH:
                return False
            self._fade_back_from = None  # 이전 복귀 페이드 취소
            self._last_scrub_packet = None
            self._mode = Mode.SCRUBBING
        if player is not None:
            # 재생 -> 일시정지 스크럽: 락 밖에서 정지+조인 (_finish_playback과 데드락 방지)
            player.stop()
            if thread is not None:
                thread.join(timeout=1.0)
        return True

    def scrub_frame(self, packet: str) -> None:
        if self.mode is not Mode.SCRUBBING:
            return
        frame = parse_packet(packet)
        if frame is not None and frame.blendshapes.get("trackingStatus") == 0:
            return  # Warudo가 무시하는 프레임: 송출 생략
        self._forward(packet)
        self._last_scrub_packet = packet

    def end_scrub(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.SCRUBBING:
                return
            self._mode = Mode.PASSTHROUGH
            if self.live_available() and self._last_scrub_packet:
                frame = parse_packet(self._last_scrub_packet)
                if frame is not None:
                    self._fade_back_from = frame
                    self._fade_back_until = (
                        time.perf_counter()
                        + self._config.crossfade_live_ms / 1000.0
                    )

    # -- 설정 적용 (GUI 스레드에서 호출) ----------------------

    def apply_config(self, new: Config) -> str | None:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return tr("err.apply_not_passthrough")
        if new.listen_port != self.bound_port:
            old_bound = self.bound_port
            self._stop_listener()
            if not self._start_listener(new.listen_port):
                error = self.bind_error
                if old_bound is not None and self._start_listener(old_bound):
                    # 롤백 성공 -- _start_listener가 bind_error를 None으로 복원
                    return tr("err.port_change_kept", error=error)
                self.bound_port = None
                return tr("err.port_change_lost", error=error)
        # 인플레이스 갱신 -- main.py가 같은 Config 인스턴스를 GUI와 공유함
        # config에는 사용자가 요청한 값을 저장한다 (0이면 매 시작마다 OS 할당 --
        # GUI 다이얼로그는 1~65535만 허용하므로 실사용에서 0은 테스트 전용)
        # GUI 다이얼로그가 0 금지(1~65535)를 보장하므로 여기서는 체크하지 않음
        self._config.listen_port = new.listen_port
        self._config.forward_host = new.forward_host
        self._config.forward_port = new.forward_port
        self._config.crossfade_live_ms = new.crossfade_live_ms
        self._config.crossfade_loop_ms = new.crossfade_loop_ms
        self._forward_addr = (new.forward_host, new.forward_port)
        return None
