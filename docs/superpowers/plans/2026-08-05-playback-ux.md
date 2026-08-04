# v2.1 재생 UX 개선 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실기 피드백 5건 반영 — 녹화 즉시 정지, 스크럽 킵얼라이브, 종료 후 처음부터 재생, 트림 구간 재생/루프, 음악 플레이어식 컨트롤 바.

**Architecture:** 코어는 recorder의 finish/save 분리와 player의 재생 구간(range) 일반화 두 가지만 확장하고(기본 인자에서 기존 동작·테스트와 완전 동일), GUI는 녹화 정지 흐름 재작성, 스크럽 킵얼라이브 QTimer, 컨트롤 바 이동/배선으로 대응한다.

**Tech Stack:** 기존과 동일 (Python 3.11, PySide6, pytest).

**스펙:** `docs/superpowers/specs/2026-08-05-playback-ux-design.md`

## Global Constraints

- 코어(qt/ 밖)는 PySide6 import 금지, 이모지 금지 (ASCII와 한글만)
- 기본 인자에서 기존 동작 불변: `stop_recording`·`stop_and_save` 시그니처/동작 유지, `play()` 기본 인자 시 기존 76개 테스트 무수정 통과
- base_ms 규칙 (스펙 §4.1): 각 바퀴에서 시작 경계가 0이면 base=0, 0보다 크면 그 바퀴 첫 프레임의 t
- 킵얼라이브 100ms, 스크럽 드래그 중에만 동작
- 자연 종료 시에만 플레이헤드 리셋(구간 시작), 정지 버튼은 위치 유지
- GUI 실행 금지, 임포트 체크는 `py -3.11 -c "..."`, pytest는 기존 인터프리터
- 커밋: 큰따옴표 금지, bash 작은따옴표, rtk 접두사, 한글 커밋 메시지

## 파일 구조

```
arkit_recorder/
  recorder.py            finish/save_to 분리 (Task 1)
  proxy.py               finish/save/discard_recording (Task 1), start_playback range (Task 2)
  player.py              range_start_ms/range_end_ms (Task 2)
  qt/main_window.py      녹화 정지 흐름 (Task 3), 컨트롤 바+구간 재생+리셋 (Task 4)
  qt/timeline_widget.py  킵얼라이브 타이머 (Task 3)
tests/
  test_recorder.py       (Task 1)  test_proxy.py (Task 1, 2)  test_player.py (Task 2)
```

---

### Task 1: recorder finish/save 분리 + proxy 녹화 API

**Files:**
- Modify: `arkit_recorder/recorder.py` (stop_and_save를 finish+save_to 조합으로 재구성)
- Modify: `arkit_recorder/proxy.py` (stop_recording을 finish+save 조합으로 재구성)
- Test: `tests/test_recorder.py`, `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Produces:
  - `ClipRecorder.finish() -> None` — 락 하 파일 close, tmp 유지. 미녹화면 무시
  - `ClipRecorder.save_to(final_path: Path) -> int` — finish 이후 전제. tmp rename, frame_count 반환, 파형 버퍼 초기화. 녹화 중이거나 tmp 부재면 0
  - `ClipRecorder.stop_and_save(final_path) -> int` — finish+save_to 조합 (동작 불변)
  - `FaceProxy.finish_recording() -> None` — RECORDING이면 recorder.finish()+PASSTHROUGH
  - `FaceProxy.save_recording(name: str) -> Path` — recorder.save_to(clips_dir/name.jsonl)
  - `FaceProxy.discard_recording() -> None` — recorder.discard()
  - `FaceProxy.stop_recording(name) -> Path` — finish_recording+save_recording 조합 (동작 불변)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_recorder.py`에 추가:

```python
def test_finish_keeps_tmp_and_ignores_feed(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.start()
    rec.feed("a-1|trackingStatus-1|=|head#0,0,0|")
    rec.finish()
    assert not rec.is_recording
    assert (tmp_path / "_tmp.jsonl").exists()
    rec.feed("a-2|trackingStatus-1|=|head#0,0,0|")  # 무시돼야 함
    assert rec.frame_count == 1
    final = tmp_path / "kept.jsonl"
    assert rec.save_to(final) == 1
    assert final.exists()
    assert not (tmp_path / "_tmp.jsonl").exists()


def test_save_to_guards(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    assert rec.save_to(tmp_path / "none.jsonl") == 0  # tmp 부재
    rec.start()
    rec.feed("a-1|trackingStatus-1|=|head#0,0,0|")
    assert rec.save_to(tmp_path / "early.jsonl") == 0  # finish 전 — 방어
    assert rec.is_recording  # 녹화 상태 유지
    rec.discard()


def test_discard_after_finish_removes_tmp(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.start()
    rec.feed("a-1|trackingStatus-1|=|head#0,0,0|")
    rec.finish()
    rec.discard()
    assert not (tmp_path / "_tmp.jsonl").exists()
```

`tests/test_proxy.py`에 추가:

```python
def test_finish_recording_stops_immediately(proxy, warudo_socket, tmp_path):
    proxy.start_recording()
    send_to_proxy(proxy)
    recv_text(warudo_socket)
    time.sleep(0.1)
    proxy.finish_recording()
    assert proxy.mode is Mode.PASSTHROUGH
    send_to_proxy(proxy)  # 정지 후 패킷 — 기록되지 않고 전달만
    assert recv_text(warudo_socket) == PACKET
    path = proxy.save_recording("late_name")
    assert path == tmp_path / "clips" / "late_name.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_discard_recording_removes_tmp(proxy, warudo_socket, tmp_path):
    proxy.start_recording()
    send_to_proxy(proxy)
    recv_text(warudo_socket)
    time.sleep(0.1)
    proxy.finish_recording()
    proxy.discard_recording()
    assert not (tmp_path / "clips" / "_recording.tmp.jsonl").exists()
```

(test_proxy.py 상단에 `import time`이 이미 있는지 확인 — 있음)

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_recorder.py tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`AttributeError: finish`)

- [ ] **Step 3: 구현**

`recorder.py` — `stop_and_save`를 다음 세 메서드로 교체:

```python
    def finish(self) -> None:
        with self._lock:
            if self._file is None:
                return
            self._file.close()
            self._file = None

    def save_to(self, final_path: Path) -> int:
        with self._lock:
            if self._file is not None:
                return 0  # finish 전 호출 방어 — 녹화 상태를 깨지 않는다
            if not self._tmp_path.exists():
                return 0
            final_path.parent.mkdir(parents=True, exist_ok=True)
            self._tmp_path.replace(final_path)
            count = self.frame_count
            self._wave.clear()
            self._prev_frame = None
            return count

    def stop_and_save(self, final_path: Path) -> int:
        if not self.is_recording:
            return 0
        self.finish()
        return self.save_to(final_path)
```

`proxy.py` — `stop_recording`을 다음으로 교체:

```python
    def finish_recording(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.RECORDING:
                return
            self._recorder.finish()
            self._mode = Mode.PASSTHROUGH

    def save_recording(self, name: str) -> Path:
        path = self.clips_dir / (name + ".jsonl")
        self._recorder.save_to(path)
        return path

    def discard_recording(self) -> None:
        self._recorder.discard()

    def stop_recording(self, name: str) -> Path:
        self.finish_recording()
        return self.save_recording(name)
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 76개 포함)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/recorder.py arkit_recorder/proxy.py tests/test_recorder.py tests/test_proxy.py
rtk git commit -m 'feat: 녹화 정지와 저장 분리'
```

---

### Task 2: player 구간 재생/루프

**Files:**
- Modify: `arkit_recorder/player.py` (play에 range 인자)
- Modify: `arkit_recorder/proxy.py` (start_playback/_run_player 전달)
- Test: `tests/test_player.py`, `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Produces:
  - `ClipPlayer.play(loop=False, lead_in_packet=None, start_ms=0, range_start_ms=0, range_end_ms=None)` — 재생 구간 [range_start_ms, range_end_ms(None=끝)]. 첫 바퀴는 max(start_ms, range_start_ms)부터, 루프 되감기는 range_start_ms부터. base_ms: 바퀴 시작 경계가 0이면 0, 아니면 그 바퀴 첫 프레임 t
  - `FaceProxy.start_playback(clip_path, loop, start_ms=0, range_start_ms=0, range_end_ms=None) -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_player.py`에 추가:

```python
def test_range_playback_only_sends_range(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate([0, 100, 200, 300])
    ])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append((clock.time, p)))
    player.load(path)
    player.play(range_start_ms=100, range_end_ms=200)
    assert [parse_packet(p).blendshapes["a"] for _, p in sent] == [1, 2]
    assert [t for t, _ in sent] == [0.0, pytest.approx(0.1)]  # 구간 첫 프레임 기준 상대


def test_range_loop_rewinds_to_range_start(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate([0, 100, 200, 300])
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) >= 4:
            player.stop()

    # 루프 크로스페이드를 끄고 순수 구간 루프만 검증
    player = make_player(clock, send, crossfade_loop_ms=0)
    player.load(path)
    player.play(loop=True, start_ms=200, range_start_ms=100, range_end_ms=200)
    values = [parse_packet(p).blendshapes["a"] for p in sent]
    # 1바퀴: start_ms=200부터 [2], 2바퀴부터 구간 시작(100)부터 [1, 2], ...
    assert values == [2, 1, 2, 1]


def test_range_without_frames_returns(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [{"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"}])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p))
    player.load(path)
    player.play(range_start_ms=500, range_end_ms=900)
    assert sent == []
    assert not player.is_playing
```

`tests/test_proxy.py`에 추가:

```python
def test_start_playback_range(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 50, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-3|trackingStatus-1|=|head#0,0,0|"},
    ])
    count = proxy.start_playback(
        clip, loop=False, range_start_ms=50, range_end_ms=100
    )
    assert count == 3  # 반환값은 전체 로드 프레임 수 (기존 의미)
    values = [
        parse_packet(recv_text(warudo_socket)).blendshapes["a"] for _ in range(2)
    ]
    assert values == [2, 3]
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_player.py tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`TypeError: play() got an unexpected keyword argument`)

- [ ] **Step 3: 구현**

`player.py` — `play`를 다음으로 교체:

```python
    def play(
        self,
        loop: bool = False,
        lead_in_packet: str | None = None,
        start_ms: int = 0,
        range_start_ms: int = 0,
        range_end_ms: int | None = None,
    ) -> None:
        # 블로킹 — 호출자는 별도 스레드에서 실행한다
        if self.is_playing:
            return
        range_frames = [
            (t, p) for t, p in self._frames
            if t >= range_start_ms and (range_end_ms is None or t <= range_end_ms)
        ]
        first_start = max(start_ms, range_start_ms)
        first_frames = (
            [(t, p) for t, p in range_frames if t >= first_start]
            if first_start > 0 else range_frames
        )
        if not first_frames:
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            frames = first_frames
            # base_ms 규칙: 바퀴 시작 경계가 0이면 0, 아니면 그 바퀴 첫 프레임 t
            base_ms = first_frames[0][0] if first_start > 0 else 0
            while not self._stop_event.is_set():
                start = self._now()
                for t_ms, packet in frames:
                    if self._stop_event.is_set():
                        return
                    rel_ms = t_ms - base_ms
                    delay = start + rel_ms / 1000.0 - self._now()
                    if delay > 0:
                        self._sleep(delay)
                    out = self._prepare(packet, rel_ms, fade_src, fade_ms)
                    if out is not None:
                        self._send(out)
                        self.last_sent_packet = out
                        self.position_ms = t_ms
                if not loop:
                    return
                # 루프 되감기는 재생 구간 시작부터 (구간 미지정 시 0 = 기존 동작)
                frames = range_frames
                base_ms = range_frames[0][0] if range_start_ms > 0 else 0
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False
```

`proxy.py` — `start_playback` 시그니처/스레드 인자와 `_run_player`를 교체:

```python
    def start_playback(
        self,
        clip_path: Path,
        loop: bool,
        start_ms: int = 0,
        range_start_ms: int = 0,
        range_end_ms: int | None = None,
    ) -> int:
        # (기존 본문 동일 — 스레드 생성부만 교체)
        self._player_thread = threading.Thread(
            target=self._run_player,
            args=(player, loop, lead_in, start_ms, range_start_ms, range_end_ms),
            daemon=True,
        )

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
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 전부 무수정)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/player.py arkit_recorder/proxy.py tests/test_player.py tests/test_proxy.py
rtk git commit -m 'feat: 재생 구간과 구간 루프'
```

---

### Task 3: GUI — 녹화 즉시 정지 흐름 + 스크럽 킵얼라이브

**Files:**
- Modify: `arkit_recorder/qt/main_window.py` (_on_record RECORDING 분기)
- Modify: `arkit_recorder/qt/timeline_widget.py` (킵얼라이브 타이머)

**Interfaces:**
- Consumes: Task 1의 `finish_recording/save_recording/discard_recording`, 기존 `scrub_frame`

- [ ] **Step 1: main_window._on_record 수정** — RECORDING 분기를 다음으로 교체:

```python
        elif mode is Mode.RECORDING:
            # 버튼 시점에 즉시 정지 (스펙 §2.3) — 이름 입력 중 프레임이 쌓이지 않게
            self._proxy.finish_recording()
            self._record_button.setText("녹화 시작")
            while True:
                name, ok = QInputDialog.getText(self, "클립 저장", "클립 이름:")
                if ok and name.strip():
                    try:
                        validate_clip_name(self._proxy.clips_dir, name)
                    except ValueError as e:
                        QMessageBox.warning(self, "클립 저장", str(e))
                        continue  # 이름 재입력
                    self._proxy.save_recording(name.strip())
                    self._refresh_clips()
                    return
                answer = QMessageBox.question(
                    self, "클립 저장", "녹화를 저장하지 않고 버릴까요?"
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self._proxy.discard_recording()
                    return
                # 아니오: 이름 다이얼로그 재표시
```

- [ ] **Step 2: timeline_widget 킵얼라이브**

import 변경: `from PySide6.QtCore import QPointF, Qt, QTimer`

`__init__` 끝에 추가:

```python
        # 스크럽 홀드 킵얼라이브 — Warudo 0.5초 무수신 트래킹 끊김 방지 (스펙 §3)
        self._keepalive = QTimer(self)
        self._keepalive.setInterval(100)
        self._keepalive.timeout.connect(self._resend_scrub)
```

`mousePressEvent`의 스크럽 시작 분기를 다음으로 교체:

```python
        if self._proxy.begin_scrub():
            self._dragging = "scrub"
            self._last_scrub_index = -1
            self._keepalive.start()
            self._scrub_to(x)
```

`mouseReleaseEvent`를 다음으로 교체:

```python
    def mouseReleaseEvent(self, event) -> None:
        if self._dragging == "scrub":
            self._keepalive.stop()
            self._proxy.end_scrub()
        self._dragging = None
```

메서드 추가:

```python
    def _resend_scrub(self) -> None:
        # 마우스가 멈춰 있어도 현재 프레임을 재전송 (내용이 같아도 Warudo는 수신 시각 갱신)
        if self._dragging != "scrub" or self._data is None:
            return
        if self._last_scrub_index < 0 or self._last_scrub_index >= len(self._data.frames):
            return
        self._proxy.scrub_frame(self._data.frames[self._last_scrub_index][1])
```

- [ ] **Step 3: 검증**

```
python -m pytest tests/ -v      → 전부 PASS (회귀 없음)
py -3.11 -c "import arkit_recorder.qt.main_window; import arkit_recorder.qt.timeline_widget; print('import ok')"
```

- [ ] **Step 4: 커밋**

```bash
rtk git add arkit_recorder/qt/main_window.py arkit_recorder/qt/timeline_widget.py
rtk git commit -m 'feat: 녹화 즉시 정지 흐름, 스크럽 킵얼라이브'
```

---

### Task 4: GUI — 플레이어 컨트롤 바 + 구간 재생 배선 + 종료 리셋

**Files:**
- Modify: `arkit_recorder/qt/main_window.py`

**Interfaces:**
- Consumes: Task 2의 `start_playback(..., range_start_ms, range_end_ms)`, 위젯의 `trim_range()/playhead_ms()/set_playhead()`

- [ ] **Step 1: 컨트롤 바 이동**

import에 `QStyle` 추가 (`QtWidgets`에서), `QCheckBox` 제거 (사용처 없어짐).

`_build_ui`의 좌측 패널에서 `play_row`(재생/정지)와 `self._loop_check` 블록을 **삭제**하고,
우측 패널의 `self._right_panel.addWidget(self._timeline, 1)` 다음에 추가:

```python
        # 음악 플레이어식 컨트롤 바 (스펙 §5) — 타임라인 아래 가운데 정렬
        controls = QHBoxLayout()
        controls.addStretch(1)
        style = self.style()
        self._play_button = QPushButton("재생")
        self._play_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self._play_button.clicked.connect(self._on_play)
        self._stop_button = QPushButton("정지")
        self._stop_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._on_stop)
        self._loop_button = QPushButton("루프")
        self._loop_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._loop_button.setCheckable(True)
        controls.addWidget(self._play_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._loop_button)
        controls.addStretch(1)
        self._right_panel.addLayout(controls)
```

- [ ] **Step 2: 상태 필드와 정지 핸들러**

`__init__`의 `self._timeline_data = None` 아래에 추가:

```python
        self._was_playing = False
        self._stopped_by_user = False
```

핸들러 추가 (`_on_play` 위):

```python
    def _on_stop(self) -> None:
        self._stopped_by_user = True  # 정지 버튼: 플레이헤드 유지 (스펙 §4.3)
        self._proxy.stop_playback()
```

- [ ] **Step 3: 구간 재생 배선**

`_start_ms_for_play`를 다음으로 교체:

```python
    def _playback_range(self) -> tuple[int, int, int | None]:
        # (start_ms, range_start_ms, range_end_ms) — 트림 구간이 재생 범위 (스펙 §4.3)
        if self._timeline_data is None:
            return 0, 0, None
        trim_start, trim_end = self._timeline.trim_range()
        playhead = self._timeline.playhead_ms()
        start = playhead if trim_start <= playhead < trim_end else trim_start
        return start, trim_start, trim_end
```

`_on_play`의 start_playback 호출을 다음으로 교체:

```python
        start_ms, range_start, range_end = self._playback_range()
        count = self._proxy.start_playback(
            info.path, self._loop_button.isChecked(),
            start_ms=start_ms, range_start_ms=range_start, range_end_ms=range_end,
        )
```

- [ ] **Step 4: 자연 종료 리셋**

`_poll`의 `busy = ...` 줄 앞에 추가:

```python
        playing = mode is Mode.PLAYING
        if self._was_playing and not playing:
            # 재생 종료 전이 — 자연 종료면 구간 시작으로 리셋 (스펙 §4.3)
            if not self._stopped_by_user:
                trim_start, _ = self._timeline.trim_range()
                self._timeline.set_playhead(trim_start)
            self._stopped_by_user = False
        self._was_playing = playing
```

- [ ] **Step 5: 검증**

```
python -m pytest tests/ -v      → 전부 PASS
py -3.11 -c "import arkit_recorder.qt.main_window; print('import ok')"
```

- [ ] **Step 6: 커밋**

```bash
rtk git add arkit_recorder/qt/main_window.py
rtk git commit -m 'feat: 플레이어 컨트롤 바, 구간 재생 배선, 종료 리셋'
```

---

## 수동 스모크 (구현 완료 후, 사용자 진행)

1. 녹화 정지 버튼 → 즉시 정지되고 이름 다이얼로그 (입력 중 프레임 안 쌓임), 취소 → 버리기 확인
2. 스크럽 홀드 → 아바타 표정 유지 (0.5초 후에도 안 풀림)
3. 재생 끝까지 → [재생] 다시 누르면 처음부터
4. 트림 구간 설정 → 재생/루프가 구간 안에서만
5. 컨트롤 바가 타임라인 아래 가운데, 루프 토글 동작
6. 정지 버튼으로 멈춘 뒤 [재생] → 그 위치부터 이어 재생
