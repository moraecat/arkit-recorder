# arkit_recorder/qt/timeline_widget.py
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..proxy import Mode
from ..timeline import (
    TimelineData, activity_curve, blendshape_curve, frame_index_at,
)

MARKER_BAND = 12   # 상단 트림 핸들 밴드(px, 스펙 §4.2) — 이 아래는 스크럽 영역
MARGIN_X = 8
GRID_COLOR = QColor("#33353a")
CURVE_COLOR = QColor("#4f9cf9")
WAVE_COLOR = QColor("#d16d6d")
PLAYHEAD_COLOR = QColor("#e8e8e8")
TRIM_COLOR = QColor("#f0c674")
TRIM_FILL = QColor(240, 198, 116, 28)
TEXT_COLOR = QColor("#9a9a9a")


class TimelineWidget(QWidget):
    def __init__(self, proxy, parent=None):
        super().__init__(parent)
        self._proxy = proxy
        self._data: TimelineData | None = None
        self._curve: list[tuple[int, float]] = []
        self._playhead_ms = 0
        self._trim_start = 0
        self._trim_end = 0
        self._live_wave: list[tuple[int, float]] | None = None
        self._dragging: str | None = None  # scrub | trim_start | trim_end
        self._last_scrub_index = -1
        self._paused = False
        self._scrub_from_playing = False
        self.setMinimumHeight(180)
        # 스크럽 홀드 킵얼라이브 — Warudo 0.5초 무수신 트래킹 끊김 방지 (스펙 §3)
        self._keepalive = QTimer(self)
        self._keepalive.setInterval(100)
        self._keepalive.timeout.connect(self._resend_scrub)

    # -- 외부 API -------------------------------------------

    def set_data(self, data: TimelineData | None) -> None:
        self._data = data
        self._playhead_ms = 0
        self._trim_start = 0
        self._trim_end = data.duration_ms if data else 0
        self.set_curve(None)

    def set_curve(self, name: str | None) -> None:
        if self._data is None or not self._data.frames:
            self._curve = []
        elif name is None:
            self._curve = activity_curve(self._data)
        else:
            self._curve = [
                (t, float(v)) for t, v in blendshape_curve(self._data, name)
            ]
        self.update()

    def set_live_wave(self, wave: list[tuple[int, float]] | None) -> None:
        self._live_wave = wave
        self.update()

    def set_playhead(self, ms: int) -> None:
        self._playhead_ms = ms
        self.update()

    def playhead_ms(self) -> int:
        return self._playhead_ms

    def trim_range(self) -> tuple[int, int]:
        return self._trim_start, self._trim_end

    def is_live(self) -> bool:
        return self._live_wave is not None

    def is_paused(self) -> bool:
        return self._paused

    def release_pause(self, end: bool) -> None:
        # 일시정지 해제 — end=True면 라이브 복귀(end_scrub), False면 모드 유지(재생 재개용)
        if not self._paused:
            return
        self._keepalive.stop()
        self._paused = False
        self._scrub_from_playing = False
        if end:
            self._proxy.end_scrub()

    # -- 좌표 변환 ------------------------------------------

    def _span_ms(self) -> int:
        if self._live_wave:
            return max((t for t, _ in self._live_wave), default=1000) or 1000
        if self._data and self._data.duration_ms > 0:
            return self._data.duration_ms
        return 1000

    def _ms_to_x(self, ms: int) -> float:
        usable = max(1, self.width() - 2 * MARGIN_X)
        return MARGIN_X + usable * ms / self._span_ms()

    def _x_to_ms(self, x: float) -> int:
        usable = max(1, self.width() - 2 * MARGIN_X)
        ratio = (x - MARGIN_X) / usable
        return round(max(0.0, min(1.0, ratio)) * self._span_ms())

    # -- 그리기 ---------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#232428"))
        if self._live_wave is not None:
            self._paint_curve(painter, self._live_wave, WAVE_COLOR)
            painter.setPen(TEXT_COLOR)
            painter.drawText(MARGIN_X + 4, 18, "녹화 중")
            return
        if self._data is None or not self._data.frames:
            painter.setPen(TEXT_COLOR)
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "프레임 없음"
            )
            return
        self._paint_grid(painter)
        self._paint_trim(painter)
        self._paint_curve(painter, self._curve, CURVE_COLOR)
        self._paint_playhead(painter)

    def _paint_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(GRID_COLOR, 1))
        span = self._span_ms()
        step = 1000
        while span / step > 20:  # 눈금이 20개를 넘으면 간격 확대
            step *= 5
            if step <= 0:
                break
        ms = 0
        while ms <= span:
            x = self._ms_to_x(ms)
            painter.drawLine(int(x), MARKER_BAND, int(x), self.height())
            painter.setPen(TEXT_COLOR)
            painter.drawText(int(x) + 2, self.height() - 4, f"{ms // 1000}s")
            painter.setPen(QPen(GRID_COLOR, 1))
            ms += step

    def _paint_curve(self, painter, curve, color) -> None:
        if not curve:
            return
        top = MARKER_BAND + 4
        bottom = self.height() - 16
        peak = max((v for _, v in curve), default=0.0) or 1.0
        points = [
            QPointF(
                self._ms_to_x(t),
                bottom - (bottom - top) * (v / peak),
            )
            for t, v in curve
        ]
        painter.setPen(QPen(color, 2))
        painter.drawPolyline(QPolygonF(points))

    def _paint_trim(self, painter: QPainter) -> None:
        x1 = self._ms_to_x(self._trim_start)
        x2 = self._ms_to_x(self._trim_end)
        painter.fillRect(
            int(x1), MARKER_BAND, int(x2 - x1), self.height() - MARKER_BAND,
            TRIM_FILL,
        )
        painter.setPen(QPen(TRIM_COLOR, 2))
        for x in (x1, x2):
            painter.drawLine(int(x), 0, int(x), self.height())
            handle = QPolygonF([
                QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, MARKER_BAND - 2),
            ])
            painter.setBrush(TRIM_COLOR)
            painter.drawPolygon(handle)

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._ms_to_x(self._playhead_ms)
        painter.setPen(QPen(PLAYHEAD_COLOR, 1))
        painter.drawLine(int(x), MARKER_BAND, int(x), self.height())

    # -- 마우스 (스크럽 / 트림) ------------------------------

    def mousePressEvent(self, event) -> None:
        if self._live_wave is not None or self._data is None or not self._data.frames:
            return
        x = event.position().x()
        if event.position().y() <= MARKER_BAND:
            # 겹침 시 오른쪽(end) 우선 — 겹친 상태에서 end를 오른쪽으로 끌어낼 수 있게
            # 트림 핸들: 가까운 쪽 마커를 잡는다 (+-8px)
            if abs(x - self._ms_to_x(self._trim_end)) <= 8:
                self._dragging = "trim_end"
                return
            if abs(x - self._ms_to_x(self._trim_start)) <= 8:
                self._dragging = "trim_start"
                return
            return
        if self._paused:
            # 일시정지 중 재탐색 — 이미 SCRUBBING 모드, begin_scrub 불필요
            self._dragging = "scrub"
            self._scrub_to(x)
            return
        self._scrub_from_playing = self._proxy.mode is Mode.PLAYING
        if self._proxy.begin_scrub():
            self._dragging = "scrub"
            self._last_scrub_index = -1
            self._keepalive.start()
            self._scrub_to(x)
        else:
            self._scrub_from_playing = False

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._dragging == "scrub":
            self._scrub_to(x)
        elif self._dragging == "trim_start":
            self._trim_start = min(self._x_to_ms(x), self._trim_end)
            self._proxy.update_playback_range(self._trim_start, self._trim_end)
            self.update()
        elif self._dragging == "trim_end":
            self._trim_end = max(self._x_to_ms(x), self._trim_start)
            self._proxy.update_playback_range(self._trim_start, self._trim_end)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging == "scrub":
            if self._paused or self._scrub_from_playing:
                # 재생 중 시작한 스크럽 -> 일시정지 유지 (킵얼라이브 계속 = 프레임 고정)
                self._paused = True
            else:
                self._keepalive.stop()
                self._proxy.end_scrub()
        self._dragging = None

    def _scrub_to(self, x: float) -> None:
        ms = self._x_to_ms(x)
        index = frame_index_at(self._data, ms)
        if index < 0:
            return
        if index != self._last_scrub_index:  # 프레임이 바뀐 경우에만 송출
            self._last_scrub_index = index
            t_ms, packet = self._data.frames[index]
            self._proxy.scrub_frame(packet)
            self._playhead_ms = t_ms
            self.update()

    def _resend_scrub(self) -> None:
        # 마우스가 멈춰 있어도 현재 프레임을 재전송 (내용이 같아도 Warudo는 수신 시각 갱신)
        if not (self._dragging == "scrub" or self._paused):
            return
        if self._data is None:
            return
        if self._last_scrub_index < 0 or self._last_scrub_index >= len(self._data.frames):
            return
        _, packet = self._data.frames[self._last_scrub_index]
        self._proxy.scrub_frame(packet)
