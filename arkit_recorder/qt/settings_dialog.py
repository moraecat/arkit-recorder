# arkit_recorder/qt/settings_dialog.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox,
)

from ..config import Config, save_config
from ..i18n import current_language, tr


def _parse_port(text: str, label: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError(tr("set.err_int", label=label))
    if not 1 <= value <= 65535:
        raise ValueError(tr("set.err_port_range", label=label))
    return value


def _parse_ms(text: str, label: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError(tr("set.err_int", label=label))
    if value < 0:
        raise ValueError(tr("set.err_ms_range", label=label))
    return value


class SettingsDialog(QDialog):
    def __init__(self, parent, proxy, config: Config, config_path: Path):
        super().__init__(parent)
        self._proxy = proxy
        self._config = config
        self._config_path = config_path
        self.setWindowTitle(tr("set.title"))
        self.setModal(True)

        form = QFormLayout(self)
        self._listen = QLineEdit(str(config.listen_port))
        self._host = QLineEdit(config.forward_host)
        self._port = QLineEdit(str(config.forward_port))
        self._live_ms = QLineEdit(str(config.crossfade_live_ms))
        self._loop_ms = QLineEdit(str(config.crossfade_loop_ms))
        form.addRow(tr("set.listen_port"), self._listen)
        form.addRow(tr("set.forward_host"), self._host)
        form.addRow(tr("set.forward_port"), self._port)
        form.addRow(tr("set.crossfade_live"), self._live_ms)
        form.addRow(tr("set.crossfade_loop"), self._loop_ms)

        self._language = QComboBox()
        self._language.addItem(tr("set.lang_auto"), "auto")
        self._language.addItem("한국어", "ko")
        self._language.addItem("English", "en")
        self._language.addItem("日本語", "ja")
        index = self._language.findData(config.language)
        self._language.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(tr("set.language"), self._language)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("set.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("set.cancel"))
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_save(self) -> None:
        listen_label = tr("set.listen_port")
        host_label = tr("set.forward_host")
        port_label = tr("set.forward_port")
        live_label = tr("set.crossfade_live")
        loop_label = tr("set.crossfade_loop")
        try:
            listen_port = _parse_port(self._listen.text(), listen_label)
            forward_host = self._host.text().strip()
            if not forward_host:
                raise ValueError(tr("set.err_host_empty"))
            forward_port = _parse_port(self._port.text(), port_label)
            live_ms = _parse_ms(self._live_ms.text(), live_label)
            loop_ms = _parse_ms(self._loop_ms.text(), loop_label)
        except ValueError as e:
            QMessageBox.warning(self, tr("set.title"), str(e))
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
            QMessageBox.warning(self, tr("set.title"), error)
            return
        # apply_config가 공유 config를 인플레이스 갱신했으므로 그대로 저장
        new_language = self._language.currentData()
        language_changed = new_language != self._config.language
        self._config.language = new_language
        save_config(self._config_path, self._config)
        if language_changed:
            QMessageBox.information(self, tr("set.title"), tr("set.restart_needed"))
        self.accept()


def open_settings(parent, proxy, config: Config, config_path: Path) -> None:
    SettingsDialog(parent, proxy, config, config_path).exec()
