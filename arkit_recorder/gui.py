# arkit_recorder/gui.py
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog

from .config import Config
from .proxy import FaceProxy, Mode

POLL_MS = 200


def run_gui(proxy: FaceProxy, config: Config) -> None:
    root = tk.Tk()
    root.title("ARKit Recorder")
    root.geometry("380x460")

    # ── 상태부 ──
    status_frame = tk.LabelFrame(root, text="상태")
    status_frame.pack(fill="x", padx=8, pady=4)
    recv_label = tk.Label(status_frame, text="수신: -", anchor="w")
    recv_label.pack(fill="x", padx=6)
    forward_label = tk.Label(
        status_frame,
        text=f"전달: {config.forward_host}:{config.forward_port}",
        anchor="w",
    )
    forward_label.pack(fill="x", padx=6)
    mode_label = tk.Label(status_frame, text="모드: -", anchor="w")
    mode_label.pack(fill="x", padx=6, pady=(0, 4))

    # ── 녹화부 ──
    record_frame = tk.LabelFrame(root, text="녹화")
    record_frame.pack(fill="x", padx=8, pady=4)
    record_button = tk.Button(record_frame, text="녹화 시작")
    record_button.pack(fill="x", padx=6, pady=4)

    # ── 재생부 ──
    play_frame = tk.LabelFrame(root, text="재생")
    play_frame.pack(fill="both", expand=True, padx=8, pady=4)
    clip_list = tk.Listbox(play_frame, height=8)
    clip_list.pack(fill="both", expand=True, padx=6, pady=4)
    loop_var = tk.BooleanVar(value=False)
    loop_check = tk.Checkbutton(play_frame, text="루프 재생", variable=loop_var)
    loop_check.pack(anchor="w", padx=6)
    button_row = tk.Frame(play_frame)
    button_row.pack(fill="x", padx=6, pady=4)
    play_button = tk.Button(button_row, text="재생")
    play_button.pack(side="left", expand=True, fill="x")
    stop_button = tk.Button(button_row, text="정지", state="disabled")
    stop_button.pack(side="left", expand=True, fill="x", padx=(6, 0))

    def refresh_clips():
        clip_list.delete(0, "end")
        if proxy.clips_dir.exists():
            for path in sorted(proxy.clips_dir.glob("*.jsonl")):
                if not path.name.startswith("_"):
                    clip_list.insert("end", path.stem)

    def on_record():
        if proxy.mode is Mode.PASSTHROUGH:
            proxy.start_recording()
            record_button.config(text="녹화 정지 (저장)")
        elif proxy.mode is Mode.RECORDING:
            name = simpledialog.askstring(
                "클립 저장", "클립 이름:", parent=root
            )
            if not name:
                return  # 이름 없이는 계속 녹화 유지
            proxy.stop_recording(name.strip())
            record_button.config(text="녹화 시작")
            refresh_clips()

    def on_play():
        selection = clip_list.curselection()
        if not selection:
            messagebox.showinfo("재생", "재생할 클립을 선택하세요.", parent=root)
            return
        name = clip_list.get(selection[0])
        count = proxy.start_playback(
            proxy.clips_dir / (name + ".jsonl"), loop_var.get()
        )
        if count == 0:
            messagebox.showwarning(
                "재생", "클립을 재생할 수 없습니다 (빈 파일 또는 녹화 중).",
                parent=root,
            )

    def on_stop():
        proxy.stop_playback()

    record_button.config(command=on_record)
    play_button.config(command=on_play)
    stop_button.config(command=on_stop)

    def poll():
        if proxy.bind_error:
            recv_label.config(text=f"오류: {proxy.bind_error}", fg="red")
        else:
            hz, since = proxy.receive_stats()
            if since is None:
                recv_label.config(text="수신: 없음 (아이폰 미연결)", fg="gray")
            elif since > 0.5:
                recv_label.config(text=f"수신: 끊김 ({since:.1f}초 전)", fg="red")
            else:
                recv_label.config(text=f"수신: {hz} Hz", fg="green")
        mode_names = {
            Mode.PASSTHROUGH: "패스스루",
            Mode.RECORDING: "녹화 중",
            Mode.PLAYING: "재생 중",
        }
        mode_label.config(text=f"모드: {mode_names[proxy.mode]}")
        playing = proxy.mode is Mode.PLAYING
        stop_button.config(state="normal" if playing else "disabled")
        play_button.config(state="disabled" if playing else "normal")
        record_button.config(
            state="disabled" if playing else "normal"
        )
        root.after(POLL_MS, poll)

    refresh_clips()
    poll()
    root.mainloop()
