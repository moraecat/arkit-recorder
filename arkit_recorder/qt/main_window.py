# arkit_recorder/qt/main_window.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..clips import delete_clip, list_clips, rename_clip, validate_clip_name
from ..config import Config
from ..proxy import FaceProxy, Mode
from ..timeline import load_timeline, save_frames, trim
from .settings_dialog import open_settings
from .timeline_widget import TimelineWidget

POLL_MS = 200

MODE_NAMES = {
    Mode.PASSTHROUGH: "패스스루",
    Mode.RECORDING: "녹화 중",
    Mode.PLAYING: "재생 중",
    Mode.SCRUBBING: "스크럽 중",
}


class MainWindow(QMainWindow):
    def __init__(self, proxy: FaceProxy, config: Config, config_path: Path):
        super().__init__()
        self._proxy = proxy
        self._config = config
        self._config_path = config_path
        self._clip_infos = []
        self._timeline_data = None
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
        self._recv_label = QLabel("수신: -")
        self._mode_label = QLabel("모드: -")
        self._forward_label = QLabel("전달: -")
        settings_button = QPushButton("설정")
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
        self._record_button = QPushButton("녹화 시작")
        self._record_button.clicked.connect(self._on_record)
        left.addWidget(self._record_button)
        play_row = QHBoxLayout()
        self._play_button = QPushButton("재생")
        self._play_button.clicked.connect(self._on_play)
        self._stop_button = QPushButton("정지")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._proxy.stop_playback)
        play_row.addWidget(self._play_button)
        play_row.addWidget(self._stop_button)
        left.addLayout(play_row)
        self._loop_check = QCheckBox("루프 재생")
        left.addWidget(self._loop_check)
        manage_row = QHBoxLayout()
        self._rename_button = QPushButton("이름 변경")
        self._rename_button.clicked.connect(self._on_rename)
        self._delete_button = QPushButton("삭제")
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
        curve_row.addWidget(QLabel("곡선:"))
        self._curve_combo = QComboBox()
        self._curve_combo.currentIndexChanged.connect(self._on_curve_changed)
        curve_row.addWidget(self._curve_combo, 1)
        self._trim_button = QPushButton("구간을 새 클립으로 저장")
        self._trim_button.clicked.connect(self._on_save_trim)
        curve_row.addWidget(self._trim_button)
        self._right_panel.addLayout(curve_row)
        self._timeline = TimelineWidget(self._proxy)
        self._right_panel.addWidget(self._timeline, 1)
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
                self._clip_list.addItem(f"{info.name} — ?")
            else:
                self._clip_list.addItem(f"{info.name} — {info.duration_s:.1f}초")
        self._clip_list.blockSignals(False)
        self._on_clip_selected(self._clip_list.currentRow())

    def _selected_info(self):
        row = self._clip_list.currentRow()
        if row < 0 or row >= len(self._clip_infos):
            QMessageBox.information(self, "클립", "클립을 선택하세요.")
            return None
        return self._clip_infos[row]

    def _on_clip_selected(self, row: int) -> None:
        from ..timeline import blendshape_names

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
        self._curve_combo.addItem("활동량")
        for name in blendshape_names(self._timeline_data):
            self._curve_combo.addItem(name)
        self._curve_combo.setCurrentIndex(0)
        self._curve_combo.blockSignals(False)

    # -- 조작 핸들러 ----------------------------------------

    def _on_record(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PASSTHROUGH:
            self._proxy.start_recording()
            self._record_button.setText("녹화 정지 (저장)")
        elif mode is Mode.RECORDING:
            name, ok = QInputDialog.getText(self, "클립 저장", "클립 이름:")
            if not ok or not name.strip():
                return  # 이름 없이는 계속 녹화 유지
            try:
                validate_clip_name(self._proxy.clips_dir, name)
            except ValueError as e:
                QMessageBox.warning(self, "클립 저장", str(e))
                return  # 녹화 유지 — 다시 시도 가능
            self._proxy.stop_recording(name.strip())
            self._record_button.setText("녹화 시작")
            self._refresh_clips()

    def _on_curve_changed(self, index: int) -> None:
        if index <= 0:
            self._timeline.set_curve(None)  # 활동량
        else:
            self._timeline.set_curve(self._curve_combo.currentText())

    def _start_ms_for_play(self) -> int:
        if self._timeline_data is None:
            return 0
        playhead = self._timeline.playhead_ms()
        if 0 < playhead < self._timeline_data.duration_ms:
            return playhead
        return 0

    def _on_save_trim(self) -> None:
        if self._timeline_data is None:
            QMessageBox.information(self, "구간 저장", "클립을 먼저 선택하세요.")
            return
        start_ms, end_ms = self._timeline.trim_range()
        frames = trim(self._timeline_data, start_ms, end_ms)
        if not frames:
            QMessageBox.warning(self, "구간 저장", "선택 구간에 프레임이 없습니다.")
            return
        name, ok = QInputDialog.getText(self, "구간 저장", "새 클립 이름:")
        if not ok or not name.strip():
            return
        try:
            path = validate_clip_name(self._proxy.clips_dir, name)
        except ValueError as e:
            QMessageBox.warning(self, "구간 저장", str(e))
            return
        save_frames(frames, path)
        self._refresh_clips()

    def _on_play(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
            return
        info = self._selected_info()
        if info is None:
            return
        count = self._proxy.start_playback(
            info.path, self._loop_check.isChecked(),
            start_ms=self._start_ms_for_play(),
        )
        if count == 0:
            QMessageBox.warning(
                self, "재생", "클립을 재생할 수 없습니다 (빈 파일 또는 녹화 중)."
            )

    def _on_rename(self) -> None:
        mode = self._proxy.mode
        if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
            return
        info = self._selected_info()
        if info is None:
            return
        name, ok = QInputDialog.getText(
            self, "이름 변경", "새 이름:", text=info.name
        )
        if not ok or not name.strip():
            return
        try:
            rename_clip(self._proxy.clips_dir, info.name, name)
        except ValueError as e:
            QMessageBox.warning(self, "이름 변경", str(e))
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
            self, "삭제", f"클립 {info.name}을(를) 삭제할까요?"
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
            self._recv_label.setText(f"오류: {proxy.bind_error}")
            self._recv_label.setStyleSheet("color: #ff6b6b;")
        else:
            hz, since = proxy.receive_stats()
            if since is None:
                self._recv_label.setText("수신: 없음 (아이폰 미연결)")
                self._recv_label.setStyleSheet("color: #9a9a9a;")
            elif since > 0.5:
                self._recv_label.setText(f"수신: 끊김 ({since:.1f}초 전)")
                self._recv_label.setStyleSheet("color: #ff6b6b;")
            else:
                self._recv_label.setText(f"수신: {hz} Hz")
                self._recv_label.setStyleSheet("color: #6dd17c;")
        mode = proxy.mode
        self._mode_label.setText(f"모드: {MODE_NAMES[mode]}")
        self._forward_label.setText(
            f"전달: {self._config.forward_host}:{self._config.forward_port}"
        )
        busy = mode is Mode.PLAYING or mode is Mode.SCRUBBING
        self._stop_button.setEnabled(mode is Mode.PLAYING)
        self._play_button.setEnabled(not busy)
        self._record_button.setEnabled(not busy)
        self._rename_button.setEnabled(not busy)
        self._delete_button.setEnabled(not busy)
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
