# 클립 관리 + 설정 기능 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GUI에서 클립 이름 변경/삭제/길이 표시와 설정(포트·크로스페이드) 변경·즉시 적용을 지원한다.

**Architecture:** 클립 파일 조작은 순수 로직 모듈 `clips.py`로, 설정 적용은 `FaceProxy.apply_config()`(리스너 재시작 포함)로 분리하고, GUI는 배선만 한다. 기존 v1 패턴(로직=테스트 가능 모듈, GUI=얇은 배선) 유지.

**Tech Stack:** Python 3.11 표준 라이브러리만. 테스트: pytest 9.

**스펙:** `docs/superpowers/specs/2026-08-04-clip-settings-design.md` (모든 수치·규칙의 원본)

## Global Constraints

- 외부 의존성 금지 — 표준 라이브러리만 (pytest는 테스트 전용)
- 코드·콘솔 출력·로그에 이모지 금지, ASCII와 한글만 (— em dash는 허용, 이모지 아님)
- 오류 메시지는 한글: 클립 검증은 ValueError, apply_config는 문자열 반환(성공 None)
- apply_config는 패스스루 모드에서만 적용, 거부 메시지 "패스스루 상태에서만 설정을 적용할 수 있습니다"
- 리스너 재시작 판단 기준: `new.listen_port != self.bound_port` (스펙 §3.2 "현재 바인드 포트와 다르면")
- Config는 인플레이스 갱신 (main.py가 같은 인스턴스를 proxy와 GUI에 공유)
- 클립 길이: 파일 끝 4096바이트에서 마지막 비어있지 않은 라인의 t(ms)/1000, 실패 시 None
- 테스트 실행: `python -m pytest tests/ -v` (프로젝트 루트 E:\Works\arkit-recorder에서)
- 커밋 메시지에 큰따옴표 금지, bash 작은따옴표, rtk 접두사 (`rtk git add`, `rtk git commit`)
- GUI를 실제로 띄우지 말 것 (`python main.py` 금지) — import 체크와 전체 스위트로 검증

## 파일 구조

```
arkit_recorder\
  clips.py             ClipInfo, list_clips, rename_clip, delete_clip (Task 1 신설)
  config.py            save_config 추가 (Task 2)
  proxy.py             리스너 추출(_start_listener/_stop_listener) + apply_config (Task 2)
  gui.py               클립 관리 배선 (Task 3), 설정 버튼 (Task 4)
  settings_dialog.py   open_settings_dialog (Task 4 신설)
main.py                run_gui에 config_path 전달 (Task 4)
tests\
  test_clips.py        (Task 1)
  test_config.py       save_config 테스트 추가 (Task 2)
  test_proxy.py        apply_config 테스트 추가 (Task 2)
```

---

### Task 1: clips.py — 클립 목록/이름 변경/삭제

**Files:**
- Create: `arkit_recorder/clips.py`
- Test: `tests/test_clips.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `ClipInfo` dataclass: `name: str`(확장자 제외), `path: Path`, `duration_s: float | None`, `size_bytes: int`
  - `list_clips(clips_dir: Path) -> list[ClipInfo]` — 밑줄 시작 제외, 이름 오름차순, 디렉토리 없으면 []
  - `rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path` — 위반 시 ValueError(한글)
  - `delete_clip(path: Path) -> None` — missing_ok

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_clips.py
import json

import pytest

from arkit_recorder.clips import delete_clip, list_clips, rename_clip


def write_clip(dir_path, name, entries):
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / (name + ".jsonl")
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return path


def test_list_clips_sorted_and_filtered(tmp_path):
    write_clip(tmp_path, "b_second", [{"t": 0, "d": "x"}, {"t": 2500, "d": "x"}])
    write_clip(tmp_path, "a_first", [{"t": 0, "d": "x"}, {"t": 1200, "d": "x"}])
    write_clip(tmp_path, "_recording.tmp", [{"t": 0, "d": "x"}])
    infos = list_clips(tmp_path)
    assert [i.name for i in infos] == ["a_first", "b_second"]
    assert infos[0].duration_s == pytest.approx(1.2)
    assert infos[1].duration_s == pytest.approx(2.5)
    assert infos[0].size_bytes > 0
    assert infos[0].path == tmp_path / "a_first.jsonl"


def test_list_clips_missing_dir(tmp_path):
    assert list_clips(tmp_path / "nope") == []


def test_duration_none_for_corrupt_last_line(tmp_path):
    (tmp_path / "bad.jsonl").write_text(
        '{"t": 0, "d": "x"}\nnot json\n', encoding="utf-8"
    )
    assert list_clips(tmp_path)[0].duration_s is None


def test_duration_none_for_empty_file(tmp_path):
    (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
    assert list_clips(tmp_path)[0].duration_s is None


def test_duration_reads_tail_of_large_file(tmp_path):
    # 4096바이트 꼬리 읽기만으로 마지막 t를 얻는지 (파일 전체 스캔 불필요 확인)
    entries = [{"t": i * 16, "d": "a" * 100} for i in range(5000)]
    write_clip(tmp_path, "big", entries)
    assert list_clips(tmp_path)[0].duration_s == pytest.approx(4999 * 16 / 1000.0)


def test_rename_clip_ok(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    new_path = rename_clip(tmp_path, "old", "new")
    assert new_path == tmp_path / "new.jsonl"
    assert new_path.exists()
    assert not (tmp_path / "old.jsonl").exists()


def test_rename_clip_strips_whitespace(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    assert rename_clip(tmp_path, "old", "  new  ") == tmp_path / "new.jsonl"


def test_rename_clip_errors(tmp_path):
    write_clip(tmp_path, "old", [{"t": 0, "d": "x"}])
    write_clip(tmp_path, "taken", [{"t": 0, "d": "x"}])
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "   ")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "_hidden")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "old", "taken")
    with pytest.raises(ValueError):
        rename_clip(tmp_path, "ghost", "new")


def test_delete_clip(tmp_path):
    path = write_clip(tmp_path, "gone", [{"t": 0, "d": "x"}])
    delete_clip(path)
    assert not path.exists()
    delete_clip(path)  # missing_ok — 예외 없음
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_clips.py -v`
예상: 전부 FAIL (`ModuleNotFoundError: arkit_recorder.clips`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/clips.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TAIL_BYTES = 4096  # 길이 계산 시 파일 끝에서 읽는 최대 바이트


@dataclass
class ClipInfo:
    name: str
    path: Path
    duration_s: float | None
    size_bytes: int


def _read_duration(path: Path) -> float | None:
    # t는 단조증가이므로 마지막 유효 라인의 t가 총 길이. 꼬리만 읽는다.
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            return int(entry["t"]) / 1000.0
        except (ValueError, KeyError, TypeError):
            return None  # 마지막 유효 라인이 손상
    return None  # 빈 파일


def list_clips(clips_dir: Path) -> list[ClipInfo]:
    if not clips_dir.exists():
        return []
    infos = []
    for path in sorted(clips_dir.glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        infos.append(
            ClipInfo(
                name=path.stem,
                path=path,
                duration_s=_read_duration(path),
                size_bytes=path.stat().st_size,
            )
        )
    return infos


def rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("클립 이름이 비어 있습니다")
    if new_name.startswith("_"):
        raise ValueError("밑줄로 시작하는 이름은 사용할 수 없습니다")
    old_path = clips_dir / (old_name + ".jsonl")
    new_path = clips_dir / (new_name + ".jsonl")
    if not old_path.exists():
        raise ValueError(f"클립을 찾을 수 없습니다: {old_name}")
    if new_path.exists():
        raise ValueError(f"같은 이름의 클립이 이미 있습니다: {new_name}")
    old_path.rename(new_path)
    return new_path


def delete_clip(path: Path) -> None:
    path.unlink(missing_ok=True)
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_clips.py -v` → 전부 PASS
이후 전체 1회: `python -m pytest tests/ -v` → 회귀 없음

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/clips.py tests/test_clips.py
rtk git commit -m 'feat: 클립 목록/이름 변경/삭제 모듈'
```

---

### Task 2: config.save_config + proxy 리스너 재시작·apply_config

**Files:**
- Modify: `arkit_recorder/config.py` (함수 추가)
- Modify: `arkit_recorder/proxy.py` (리스너 추출 리팩토링 + apply_config)
- Test: `tests/test_config.py`, `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Consumes: 기존 `Config`, `FaceProxy` (v1)
- Produces:
  - `save_config(path: Path, config: Config) -> None`
  - `FaceProxy.apply_config(new: Config) -> str | None` — 성공 None, 실패 시 한글 메시지. 패스스루에서만 허용. forward/크로스페이드 즉시 반영(인플레이스), `new.listen_port != self.bound_port`면 리스너 재시작(실패 시 이전 바인드 포트로 롤백)
  - 내부: `_start_listener(port) -> bool`, `_stop_listener()` — `start()`/`stop()`이 이를 사용하도록 리팩토링. `_recv_loop(sock, stop)` 시그니처로 변경 (재시작 시 이전 스레드가 새 소켓을 건드리지 않도록 소켓/정지 이벤트를 인자로 받음)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_config.py`에 추가:

```python
from arkit_recorder.config import save_config


def test_save_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    config = Config(listen_port=15000, crossfade_live_ms=700)
    save_config(path, config)
    assert load_config(path) == config
```

`tests/test_proxy.py`에 추가 (기존 fixture/헬퍼 `proxy`, `warudo_socket`, `send_to_proxy`, `recv_text`, `make_clip`, `wait_until`, `PACKET` 재사용):

```python
def test_apply_config_forward_change(proxy, warudo_socket):
    new_warudo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    new_warudo.bind(("127.0.0.1", 0))
    new_warudo.settimeout(2.0)
    try:
        new = Config(
            listen_port=proxy.bound_port,  # 현재 바인드 포트 그대로 -> 재시작 없음
            forward_port=new_warudo.getsockname()[1],
            crossfade_live_ms=2000,
        )
        assert proxy.apply_config(new) is None
        send_to_proxy(proxy)
        data, _ = new_warudo.recvfrom(65535)
        assert data.decode("ascii") == PACKET
    finally:
        new_warudo.close()


def test_apply_config_crossfade_applies_to_next_playback(proxy, warudo_socket):
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=700,
        crossfade_loop_ms=900,
    )
    assert proxy.apply_config(new) is None
    clip = make_clip(proxy, [{"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"}])
    assert proxy.start_playback(clip, loop=False) == 1
    player = proxy._player
    assert player._crossfade_live_ms == 700
    assert player._crossfade_loop_ms == 900
    recv_text(warudo_socket)
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_apply_config_listen_port_restart(proxy, warudo_socket):
    old_bound = proxy.bound_port
    new = Config(
        listen_port=0,  # 0 != bound_port -> 재시작 (새 OS 할당 포트)
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    assert proxy.apply_config(new) is None
    assert proxy.bind_error is None
    assert proxy.bound_port is not None
    send_to_proxy(proxy)  # send_to_proxy는 갱신된 bound_port를 사용
    assert recv_text(warudo_socket) == PACKET
    assert old_bound is not None  # (참고용 — 값 비교는 OS 재할당 가능성 때문에 안 함)


def test_apply_config_rejected_while_recording(proxy, warudo_socket):
    proxy.start_recording()
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    error = proxy.apply_config(new)
    assert error is not None and "패스스루" in error
    proxy.stop_recording("cleanup")


def test_apply_config_rejected_while_playing(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 30, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=True)  # 루프로 재생 상태 유지
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    error = proxy.apply_config(new)
    assert error is not None and "패스스루" in error
    proxy.stop_playback()
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_apply_config_rollback_on_bind_failure(proxy, warudo_socket):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    try:
        new = Config(
            listen_port=blocker.getsockname()[1],  # 사용 중인 포트
            forward_port=warudo_socket.getsockname()[1],
            crossfade_live_ms=2000,
        )
        error = proxy.apply_config(new)
        assert error is not None and "이전 포트 유지" in error
        assert proxy.bind_error is None  # 롤백 성공으로 복원됨
        send_to_proxy(proxy)  # 이전 포트로 계속 수신
        assert recv_text(warudo_socket) == PACKET
    finally:
        blocker.close()
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_config.py tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`ImportError: save_config`, `AttributeError: apply_config`)

- [ ] **Step 3: 구현**

`arkit_recorder/config.py`에 추가:

```python
def save_config(path: Path, config: Config) -> None:
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
```

`arkit_recorder/proxy.py` 수정. `__init__`에 추가:

```python
        self._recv_stop = threading.Event()  # 리스너 전용 정지 (재시작 시 교체됨)
```

`start()`/`stop()`을 다음으로 교체 (bind 실패 시 send 소켓은 이제 stop()에서만 닫음 — main.py가 finally로 stop()을 보장):

```python
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
            self.bind_error = (
                f"포트 {port} 바인드 실패 "
                f"(다른 프로그램이 사용 중일 수 있음): {e}"
            )
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
        self._recv_stop.set()
        if self._recv_socket is not None:
            self._recv_socket.close()
            self._recv_socket = None
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=2.0)
            self._recv_thread = None
```

`_recv_loop` 시그니처와 종료 조건 변경 (몸통의 수신 처리 로직은 그대로 유지):

```python
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
            if mode is Mode.PLAYING:
                continue  # 재생 중엔 라이브 전달 차단 (수신 통계만 갱신)
            out = self._apply_fade_back(packet, now)
            self._forward(out)
            if mode is Mode.RECORDING:
                self._recorder.feed(packet)  # 페이드 보정 전 원본을 기록
```

`apply_config` 추가 (stop_playback 아래에):

```python
    # -- 설정 적용 (GUI 스레드에서 호출) ----------------------

    def apply_config(self, new: Config) -> str | None:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return "패스스루 상태에서만 설정을 적용할 수 있습니다"
        if new.listen_port != self.bound_port:
            old_bound = self.bound_port
            self._stop_listener()
            if not self._start_listener(new.listen_port):
                error = self.bind_error
                if old_bound is not None:
                    # 롤백 — 성공하면 _start_listener가 bind_error를 None으로 복원
                    self._start_listener(old_bound)
                return f"수신 포트 변경 실패, 이전 포트 유지: {error}"
        # 인플레이스 갱신 — main.py가 같은 Config 인스턴스를 GUI와 공유함
        self._config.listen_port = new.listen_port
        self._config.forward_host = new.forward_host
        self._config.forward_port = new.forward_port
        self._config.crossfade_live_ms = new.crossfade_live_ms
        self._config.crossfade_loop_ms = new.crossfade_loop_ms
        self._forward_addr = (new.forward_host, new.forward_port)
        return None
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 38개 + 신규, 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/config.py arkit_recorder/proxy.py tests/test_config.py tests/test_proxy.py
rtk git commit -m 'feat: 설정 저장과 apply_config, 리스너 재시작'
```

---

### Task 3: GUI 클립 관리 배선

**Files:**
- Modify: `arkit_recorder/gui.py`

**Interfaces:**
- Consumes: Task 1의 `list_clips`, `rename_clip`, `delete_clip`, `ClipInfo`
- Produces: GUI 동작 — 목록에 `이름 — 12.3초` 표시(None이면 `이름 — ?`), [이름 변경]/[삭제] 버튼, 재생 중 비활성. 재생/관리는 표시 문자열이 아닌 ClipInfo를 참조

- [ ] **Step 1: gui.py 수정**

import에 추가:

```python
from .clips import list_clips, rename_clip, delete_clip
```

`refresh_clips`를 다음으로 교체하고, 직전에 상태 변수 선언 추가:

```python
    clip_infos = []

    def refresh_clips():
        nonlocal clip_infos
        clip_infos = list_clips(proxy.clips_dir)
        clip_list.delete(0, "end")
        for info in clip_infos:
            if info.duration_s is None:
                clip_list.insert("end", f"{info.name} — ?")
            else:
                clip_list.insert("end", f"{info.name} — {info.duration_s:.1f}초")

    def selected_info():
        selection = clip_list.curselection()
        if not selection:
            messagebox.showinfo("클립", "클립을 선택하세요.", parent=root)
            return None
        return clip_infos[selection[0]]
```

(참고: `clip_infos = []`는 `run_gui` 본문에서 `refresh_clips` 정의보다 앞이면 어디든 좋다.
`nonlocal`이 동작하려면 함수 밖 지역 변수여야 한다.)

`on_play`의 선택 처리 부분을 `selected_info()` 사용으로 교체:

```python
    def on_play():
        if proxy.mode is Mode.PLAYING:
            return
        info = selected_info()
        if info is None:
            return
        count = proxy.start_playback(info.path, loop_var.get())
        if count == 0:
            messagebox.showwarning(
                "재생", "클립을 재생할 수 없습니다 (빈 파일 또는 녹화 중).",
                parent=root,
            )
```

재생부 button_row 아래에 관리 버튼 행 추가 (loop_check pack 다음, 기존 button_row 정의 그대로 유지):

```python
    manage_row = tk.Frame(play_frame)
    manage_row.pack(fill="x", padx=6, pady=(0, 4))
    rename_button = tk.Button(manage_row, text="이름 변경")
    rename_button.pack(side="left", expand=True, fill="x")
    delete_button = tk.Button(manage_row, text="삭제")
    delete_button.pack(side="left", expand=True, fill="x", padx=(6, 0))
```

핸들러 추가 및 배선 (`on_stop` 아래):

```python
    def on_rename():
        if proxy.mode is Mode.PLAYING:
            return
        info = selected_info()
        if info is None:
            return
        new_name = simpledialog.askstring(
            "이름 변경", "새 이름:", initialvalue=info.name, parent=root
        )
        if not new_name:
            return
        try:
            rename_clip(proxy.clips_dir, info.name, new_name)
        except ValueError as e:
            messagebox.showwarning("이름 변경", str(e), parent=root)
            return
        refresh_clips()

    def on_delete():
        if proxy.mode is Mode.PLAYING:
            return
        info = selected_info()
        if info is None:
            return
        if not messagebox.askyesno(
            "삭제", f"클립 {info.name}을(를) 삭제할까요?", parent=root
        ):
            return
        delete_clip(info.path)
        refresh_clips()

    rename_button.config(command=on_rename)
    delete_button.config(command=on_delete)
```

`poll()`의 버튼 상태 갱신에 추가 (record_button 갱신 다음):

```python
        rename_button.config(state="disabled" if playing else "normal")
        delete_button.config(state="disabled" if playing else "normal")
```

- [ ] **Step 2: 검증**

```
python -m pytest tests/ -v          → 전부 PASS (회귀 없음)
python -c "import arkit_recorder.gui; print('import ok')"
```

GUI 실행 금지 (수동 스모크는 사용자 몫).

- [ ] **Step 3: 커밋**

```bash
rtk git add arkit_recorder/gui.py
rtk git commit -m 'feat: GUI 클립 이름 변경/삭제/길이 표시'
```

---

### Task 4: 설정 다이얼로그 + GUI/main 배선

**Files:**
- Create: `arkit_recorder/settings_dialog.py`
- Modify: `arkit_recorder/gui.py` (설정 버튼, 전달 라벨 갱신, run_gui 시그니처)
- Modify: `main.py` (config_path 전달)

**Interfaces:**
- Consumes: Task 2의 `save_config`, `FaceProxy.apply_config`
- Produces:
  - `open_settings_dialog(parent, proxy: FaceProxy, config: Config, config_path: Path) -> None`
  - `run_gui(proxy: FaceProxy, config: Config, config_path: Path) -> None` (시그니처 변경)

- [ ] **Step 1: settings_dialog.py 작성**

```python
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
```

- [ ] **Step 2: gui.py 배선**

import에 추가 (기존 import 아래):

```python
from pathlib import Path

from .settings_dialog import open_settings_dialog
```

`run_gui` 시그니처 변경:

```python
def run_gui(proxy: FaceProxy, config: Config, config_path: Path) -> None:
```

상태부 mode_label 아래에 설정 버튼 추가:

```python
    settings_button = tk.Button(
        status_frame,
        text="설정",
        command=lambda: open_settings_dialog(root, proxy, config, config_path),
    )
    settings_button.pack(fill="x", padx=6, pady=(0, 4))
```

`poll()`에서 전달 라벨을 매 틱 갱신하도록 추가 (설정 변경 반영, recv_label 갱신 블록 다음):

```python
        forward_label.config(
            text=f"전달: {config.forward_host}:{config.forward_port}"
        )
```

- [ ] **Step 3: main.py 수정**

```python
def main() -> None:
    config_path = BASE_DIR / "config.json"
    config = load_config(config_path)
    proxy = FaceProxy(config, BASE_DIR)
    proxy.start()
    try:
        run_gui(proxy, config, config_path)
    finally:
        proxy.stop()
```

- [ ] **Step 4: 검증**

```
python -m pytest tests/ -v          → 전부 PASS (회귀 없음)
python -c "import arkit_recorder.gui; import arkit_recorder.settings_dialog; import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('import ok')"
```

GUI 실행 금지 (수동 스모크는 사용자 몫).

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/settings_dialog.py arkit_recorder/gui.py main.py
rtk git commit -m 'feat: 설정 다이얼로그와 GUI 배선'
```

---

## 수동 스모크 (구현 완료 후, 사용자 진행)

1. `python main.py` — 클립 목록에 `이름 — 길이초` 표시
2. 클립 선택 → 이름 변경 (충돌 이름 시 경고), 삭제 (확인 대화상자)
3. 설정 → 전달 포트 변경 저장 → 상태부 전달 라벨 갱신 확인
4. 설정 → 수신 포트 변경 저장 → 아이폰 앱 그대로 두고 수신 끊김 표시 확인 후 원복
5. 재생 중 설정 저장 시 거부 메시지 확인
