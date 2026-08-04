# arkit_recorder/settings_dialog.py
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from .config import Config, save_config
from .proxy import FaceProxy


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


def open_settings_dialog(
    parent, proxy: FaceProxy, config: Config, config_path: Path
) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("설정")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    fields = [
        ("수신 포트", str(config.listen_port)),
        ("전달 호스트", config.forward_host),
        ("전달 포트", str(config.forward_port)),
        ("크로스페이드 라이브(ms)", str(config.crossfade_live_ms)),
        ("크로스페이드 루프(ms)", str(config.crossfade_loop_ms)),
    ]
    entries = []
    for row, (label, value) in enumerate(fields):
        tk.Label(dialog, text=label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=8, pady=3
        )
        entry = tk.Entry(dialog, width=18)
        entry.insert(0, value)
        entry.grid(row=row, column=1, padx=8, pady=3)
        entries.append(entry)

    def on_save():
        try:
            listen_port = _parse_port(entries[0].get(), "수신 포트")
            forward_host = entries[1].get().strip()
            if not forward_host:
                raise ValueError("전달 호스트: 비어 있을 수 없습니다")
            forward_port = _parse_port(entries[2].get(), "전달 포트")
            live_ms = _parse_ms(entries[3].get(), "크로스페이드 라이브(ms)")
            loop_ms = _parse_ms(entries[4].get(), "크로스페이드 루프(ms)")
        except ValueError as e:
            messagebox.showwarning("설정", str(e), parent=dialog)
            return
        new = Config(
            listen_port=listen_port,
            forward_host=forward_host,
            forward_port=forward_port,
            clips_dir=config.clips_dir,
            crossfade_live_ms=live_ms,
            crossfade_loop_ms=loop_ms,
        )
        error = proxy.apply_config(new)
        if error is not None:
            messagebox.showwarning("설정", error, parent=dialog)
            return
        # apply_config가 공유 config를 인플레이스 갱신했으므로 그대로 저장
        save_config(config_path, config)
        dialog.destroy()

    button_row = tk.Frame(dialog)
    button_row.grid(row=len(fields), column=0, columnspan=2, pady=8)
    tk.Button(button_row, text="저장", width=10, command=on_save).pack(
        side="left", padx=4
    )
    tk.Button(button_row, text="취소", width=10, command=dialog.destroy).pack(
        side="left", padx=4
    )
