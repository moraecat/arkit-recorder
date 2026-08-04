# arkit_recorder/qt/settings_dialog.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox,
)

from ..config import Config, save_config


def _parse_port(text: str, label: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError(f"{label}: 정수를 입력하세요")
    if not 1 <= value <= 65535:
        raise ValueError(f"{label}: 1~65535 범위여야 합니다")
    return value


def _parse_ms(text: str, label: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError(f"{label}: 정수를 입력하세요")
    if value < 0:
        raise ValueError(f"{label}: 0 이상이어야 합니다")
    return value


class SettingsDialog(QDialog):
    def __init__(self, parent, proxy, config: Config, config_path: Path):
        super().__init__(parent)
        self._proxy = proxy
        self._config = config
        self._config_path = config_path
        self.setWindowTitle("설정")
        self.setModal(True)

        form = QFormLayout(self)
        self._listen = QLineEdit(str(config.listen_port))
        self._host = QLineEdit(config.forward_host)
        self._port = QLineEdit(str(config.forward_port))
        self._live_ms = QLineEdit(str(config.crossfade_live_ms))
        self._loop_ms = QLineEdit(str(config.crossfade_loop_ms))
        form.addRow("수신 포트", self._listen)
        form.addRow("전달 호스트", self._host)
        form.addRow("전달 포트", self._port)
        form.addRow("크로스페이드 라이브(ms)", self._live_ms)
        form.addRow("크로스페이드 루프(ms)", self._loop_ms)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_save(self) -> None:
        try:
            listen_port = _parse_port(self._listen.text(), "수신 포트")
            forward_host = self._host.text().strip()
            if not forward_host:
                raise ValueError("전달 호스트: 비어 있을 수 없습니다")
            forward_port = _parse_port(self._port.text(), "전달 포트")
            live_ms = _parse_ms(self._live_ms.text(), "크로스페이드 라이브(ms)")
            loop_ms = _parse_ms(self._loop_ms.text(), "크로스페이드 루프(ms)")
        except ValueError as e:
            QMessageBox.warning(self, "설정", str(e))
            return
        new = Config(
            listen_port=listen_port,
            forward_host=forward_host,
            forward_port=forward_port,
            clips_dir=self._config.clips_dir,
            crossfade_live_ms=live_ms,
            crossfade_loop_ms=loop_ms,
        )
        error = self._proxy.apply_config(new)
        if error is not None:
            QMessageBox.warning(self, "설정", error)
            return
        # apply_config가 공유 config를 인플레이스 갱신했으므로 그대로 저장
        save_config(self._config_path, self._config)
        self.accept()


def open_settings(parent, proxy, config: Config, config_path: Path) -> None:
    SettingsDialog(parent, proxy, config, config_path).exec()
