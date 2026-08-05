# arkit_recorder/qt/main_window.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from ..clips import delete_clip, list_clips, rename_clip, validate_clip_name
from ..config import Config
from ..i18n import tr
from ..proxy import FaceProxy, Mode
from ..timeline import load_timeline, save_frames, trim
from .settings_dialog import open_settings
from .timeline_widget import TimelineWidget

POLL_MS = 200

MODE_KEYS = {
    Mode.PASSTHROUGH: "mode.passthrough",
    Mode.RECORDING: "mode.recording",
    Mode.PLAYING: "mode.playing",
    Mode.SCRUBBING: "mode.scrubbing",
}


class MainWindow(QMainWindow):
    def __init__(self, proxy: FaceProxy, config: Config, config_path: Path):
        super().__init__()
        self._proxy = proxy
        self._config = config
        self._config_path = config_path
        self._clip_infos = []
        self._timeline_data = None
        self._was_playing = False
        self._stopped_by_user = False
        self.setWindowTitle("ARKit Recorder")
        self.resize(900, 480)
        self._build_ui()
        self._refresh_clips()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(POLL_MS)
        self._wave_timer = QTimer(self)
        self._wave_timer.timeout.connect(self._poll_wave)
        self._wave_timer.start(100)

    # -- UI 구성 --------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 상단 바
        top = QHBoxLayout()
        self._recv_label = QLabel(tr("label.recv_placeholder"))
        self._mode_label = QLabel(tr("label.mode_placeholder"))
        self._forward_label = QLabel(tr("label.forward_placeholder"))
        settings_button = QPushButton(tr("btn.settings"))
        settings_button.clicked.connect(self._on_settings)
        top.addWidget(self._recv_label)
        top.addSpacing(16)
        top.addWidget(self._mode_label)
        top.addSpacing(16)
        top.addWidget(self._forward_label)
        top.addStretch(1)
        top.addWidget(settings_button)
        root.addLayout(top)

        # 본문: 좌측 패널 + 우측 타임라인
        body = QHBoxLayout()
        root.addLayout(body, 1)

        left = QVBoxLayout()
        self._clip_list = QListWidget()
        self._clip_list.currentRowChanged.connect(self._on_clip_selected)
        left.addWidget(self._clip_list, 1)
        self._record_button = QPushButton(tr("btn.record_start"))
        self._record_button.clicked.connect(self._on_record)
        left.addWidget(self._record_button)
        manage_row = QHBoxLayout()
        self._rename_button = QPushButton(tr("btn.rename"))
        self._rename_button.clicked.connect(self._on_rename)
        self._delete_button = QPushButton(tr("btn.delete"))
        self._delete_button.clicked.connect(self._on_delete)
        manage_row.addWidget(self._rename_button)
        manage_row.addWidget(self._delete_button)
        left.addLayout(manage_row)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(280)
        body.addWidget(left_widget)

        # 우측: 곡선 선택 + 타임라인 + 트림 저장
        self._right_panel = QVBoxLayout()
        curve_row = QHBoxLayout()
        curve_row.addWidget(QLabel(tr("label.curve")))
        self._curve_combo = QComboBox()
        self._curve_combo.currentIndexChanged.connect(self._on_curve_changed)
        curve_row.addWidget(self._curve_combo, 1)
        self._trim_button = QPushButton(tr("btn.save_trim"))
        self._trim_button.clicked.connect(self._on_save_trim)
        curve_row.addWidget(self._trim_button)
        self._right_panel.addLayout(curve_row)
        self._timeline = TimelineWidget(self._proxy)
        self._right_panel.addWidget(self._timeline, 1)
        # 음악 플레이어식 컨트롤 바 (스펙 §5) — 타임라인 아래 가운데 정렬
        controls = QHBoxLayout()
        controls.addStretch(1)
        style = self.style()
        self._play_button = QPushButton(tr("btn.play"))
        self._play_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self._play_button.clicked.connect(self._on_play)
        self._pause_button = QPushButton(tr("btn.pause"))
        self._pause_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self._pause_button.setCheckable(True)
        self._pause_button.setEnabled(False)
        self._pause_button.clicked.connect(self._on_pause)
        self._stop_button = QPushButton(tr("btn.stop"))
        self._stop_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._on_stop)
        self._loop_button = QPushButton(tr("btn.loop"))
        self._loop_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._loop_button.setCheckable(True)
        controls.addWidget(self._play_button)
        controls.addWidget(self._pause_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._loop_button)
        controls.addStretch(1)
        self._right_panel.addLayout(controls)
        right_widget = QWidget()
        right_widget.setLayout(self._right_panel)
        body.addWidget(right_widget, 1)

    # -- 클립 목록 ------------------------------------------

    def _refresh_clips(self) -> None:
        self._clip_infos = list_clips(self._proxy.clips_dir)
        self._clip_list.blockSignals(True)
        self._clip_list.clear()
        for info in self._clip_infos:
            if info.duration_s is None:
                self._clip_list.addItem(tr("clip.item_unknown", name=info.name))
            else:
                self._clip_list.addItem(tr("clip.item", name=info.name, seconds=info.duration_s))
        self._clip_list.blockSignals(False)
        self._on_clip_selected(self._clip_list.currentRow())

    def _selected_info(self):
        row = self._clip_list.currentRow()
        if row < 0 or row >= len(self._clip_infos):
            QMessageBox.information(self, tr("dlg.clip.title"), tr("dlg.clip.select"))
            return None
        return self._clip_infos[row]

    def _on_clip_selected(self, row: int) -> None:
        from ..timeline import blendshape_names

        if self._timeline.is_paused():
            self._timeline.release_pause(end=True)  # 이전 클립 프레임 고정 해제
        if row < 0 or row >= len(self._clip_infos):
            self._timeline_data = None
            self._timeline.set_data(None)
            self._curve_combo.blockSignals(True)
            self._curve_combo.clear()
            self._curve_combo.blockSignals(False)
            return
        self._timeline_data = load_timeline(self._clip_infos[row].path)
        self._timeline.set_data(self._timeline_data)
        self._curve_combo.blockSignals(True)
        self._curve_combo.clear()
        self._curve_combo.addItem(tr("curve.activity"))
        for name in blendshape_names(self._timeline_data):
            self._curve_combo.addItem(name)
        self._curve_combo.setCurrentIndex(0)
        self._curve_combo.blockSignals(False)

    # -- 조작 핸들러 ----------------------------------------

    def _on_record(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PASSTHROUGH:
            self._proxy.start_recording()
            self._record_button.setText(tr("btn.record_stop"))
        elif mode is Mode.RECORDING:
            # 버튼 시점에 즉시 정지 (스펙 §2.3) — 이름 입력 중 프레임이 쌓이지 않게
            try:
                self._proxy.finish_recording()
            except OSError as e:
                QMessageBox.warning(self, tr("dlg.record_stop.title"), tr("dlg.record_stop.failed", error=e))
                return
            self._record_button.setText(tr("btn.record_start"))
            while True:
                name, ok = QInputDialog.getText(self, tr("dlg.save_clip.title"), tr("dlg.save_clip.prompt"))
                if ok and name.strip():
                    try:
                        validate_clip_name(self._proxy.clips_dir, name)
                    except ValueError as e:
                        QMessageBox.warning(self, tr("dlg.save_clip.title"), str(e))
                        continue  # 이름 재입력
                    self._proxy.save_recording(name.strip())
                    self._refresh_clips()
                    return
                answer = QMessageBox.question(
                    self, tr("dlg.save_clip.title"), tr("dlg.save_clip.discard")
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self._proxy.discard_recording()
                    return
                # 아니오: 이름 다이얼로그 재표시

    def _on_curve_changed(self, index: int) -> None:
        if index <= 0:
            self._timeline.set_curve(None)  # 활동량
        else:
            self._timeline.set_curve(self._curve_combo.currentText())

    def _on_pause(self, checked: bool) -> None:
        if checked:
            # 재생 중에만 일시정지 진입 가능
            if self._proxy.mode is Mode.PLAYING:
                if not self._timeline.pause_at_playhead():
                    self._pause_button.setChecked(False)
            else:
                self._pause_button.setChecked(False)
        else:
            if self._timeline.is_paused():
                self._on_play()  # 일시정지 해제 = 그 위치부터 재개

    def _on_stop(self) -> None:
        if self._timeline.is_paused():
            self._timeline.release_pause(end=True)  # 일시정지 해제 -> 라이브 복귀
            return
        self._stopped_by_user = True  # 정지 버튼: 플레이헤드 유지 (스펙 §4.3)
        self._proxy.stop_playback()

    def _playback_range(self) -> tuple[int, int, int | None]:
        # (start_ms, range_start_ms, range_end_ms) — 트림 구간이 재생 범위 (스펙 §4.3)
        if self._timeline_data is None:
            return 0, 0, None
        trim_start, trim_end = self._timeline.trim_range()
        playhead = self._timeline.playhead_ms()
        start = playhead if trim_start <= playhead < trim_end else trim_start
        return start, trim_start, trim_end

    def _on_save_trim(self) -> None:
        if self._timeline_data is None:
            QMessageBox.information(self, tr("dlg.trim.title"), tr("dlg.trim.select_first"))
            return
        start_ms, end_ms = self._timeline.trim_range()
        frames = trim(self._timeline_data, start_ms, end_ms)
        if not frames:
            QMessageBox.warning(self, tr("dlg.trim.title"), tr("dlg.trim.empty"))
            return
        name, ok = QInputDialog.getText(self, tr("dlg.trim.title"), tr("dlg.trim.prompt"))
        if not ok or not name.strip():
            return
        try:
            path = validate_clip_name(self._proxy.clips_dir, name)
        except ValueError as e:
            QMessageBox.warning(self, tr("dlg.trim.title"), str(e))
            return
        save_frames(frames, path)
        self._refresh_clips()

    def _on_play(self) -> None:
        mode = self._proxy.mode
        paused = self._timeline.is_paused()
        if mode is Mode.PLAYING or (mode is Mode.SCRUBBING and not paused):
            return
        if paused:
            self._timeline.release_pause(end=False)  # 재개 — start_playback이 직전환
        info = self._selected_info()
        if info is None:
            if paused:
                self._proxy.end_scrub()  # 클립 없음 — 일시정지 완전 해제
            return
        start_ms, range_start, range_end = self._playback_range()
        count = self._proxy.start_playback(
            info.path, self._loop_button.isChecked(),
            start_ms=start_ms, range_start_ms=range_start, range_end_ms=range_end,
        )
        if count == 0:
            if paused:
                self._proxy.end_scrub()  # 재개 실패 — 일시정지 완전 해제
            QMessageBox.warning(
                self, tr("dlg.play.title"), tr("dlg.play.failed")
            )

    def _on_rename(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
            return
        info = self._selected_info()
        if info is None:
            return
        name, ok = QInputDialog.getText(
            self, tr("dlg.rename.title"), tr("dlg.rename.prompt"), text=info.name
        )
        if not ok or not name.strip():
            return
        try:
            rename_clip(self._proxy.clips_dir, info.name, name)
        except ValueError as e:
            QMessageBox.warning(self, tr("dlg.rename.title"), str(e))
            return
        self._refresh_clips()

    def _on_delete(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
            return
        info = self._selected_info()
        if info is None:
            return
        answer = QMessageBox.question(
            self, tr("dlg.delete.title"), tr("dlg.delete.confirm", name=info.name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_clip(info.path)
        self._refresh_clips()

    def _on_settings(self) -> None:
        open_settings(self, self._proxy, self._config, self._config_path)

    # -- 폴링 -----------------------------------------------

    def _poll(self) -> None:
        proxy = self._proxy
        if proxy.bind_error:
            self._recv_label.setText(tr("label.error", error=proxy.bind_error))
            self._recv_label.setStyleSheet("color: #ff6b6b;")
        else:
            hz, since = proxy.receive_stats()
            if since is None:
                self._recv_label.setText(tr("label.recv_none"))
                self._recv_label.setStyleSheet("color: #9a9a9a;")
            elif since > 0.5:
                self._recv_label.setText(tr("label.recv_stale", seconds=since))
                self._recv_label.setStyleSheet("color: #ff6b6b;")
            else:
                self._recv_label.setText(tr("label.recv_hz", hz=hz))
                self._recv_label.setStyleSheet("color: #6dd17c;")
        mode = proxy.mode
        paused = self._timeline.is_paused()
        if paused:
            self._mode_label.setText(tr("label.mode", mode=tr("mode.paused")))
        else:
            self._mode_label.setText(tr("label.mode", mode=tr(MODE_KEYS[mode])))
        self._forward_label.setText(
            tr("label.forward", host=self._config.forward_host,
               port=self._config.forward_port)
        )
        playing = mode is Mode.PLAYING
        if self._was_playing and not playing:
            # 재생 종료 전이 — 자연 종료(PASSTHROUGH 복귀)일 때만 구간 시작으로 리셋
            if not self._stopped_by_user and mode is Mode.PASSTHROUGH:
                trim_start, _ = self._timeline.trim_range()
                self._timeline.set_playhead(trim_start)
            self._stopped_by_user = False
        self._was_playing = playing
        busy = mode is Mode.PLAYING or (mode is Mode.SCRUBBING and not paused)
        # clicked는 사용자 클릭에만 발화하므로 setChecked와 충돌 없음
        self._pause_button.setChecked(paused)
        self._pause_button.setEnabled(mode is Mode.PLAYING or paused)
        self._stop_button.setEnabled(mode is Mode.PLAYING or paused)
        self._play_button.setEnabled(not busy)
        self._record_button.setEnabled(not busy and not paused)
        self._rename_button.setEnabled(not busy and not paused)
        self._delete_button.setEnabled(not busy and not paused)
        if mode is Mode.RECORDING:
            self._trim_button.setEnabled(False)
        else:
            if self._timeline.is_live():
                self._timeline.set_live_wave(None)  # 녹화 종료 -> 클립 표시 복귀
            self._trim_button.setEnabled(not busy)
            position = self._proxy.playback_position_ms()
            if position is not None:
                self._timeline.set_playhead(position)

    def _poll_wave(self) -> None:
        # 녹화 파형은 100ms 주기로 갱신 (스펙 §3)
        if self._proxy.mode is Mode.RECORDING:
            self._timeline.set_live_wave(self._proxy.live_wave())
