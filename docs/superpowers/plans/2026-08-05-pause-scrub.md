# v2.2 루프 표시 + 실시간 구간 + 일시정지 스크럽 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 루프 토글 시각화, 트림 구간의 재생 중 실시간 반영, 재생 중 스크럽 시 일시정지(프레임 고정) 전환.

**Architecture:** 코어는 player의 동적 구간(set_range)과 proxy의 스크럽/재생 전이 확장 두 가지. "일시정지"는 새 Mode 없이 SCRUBBING + 위젯 paused 플래그 + 킵얼라이브 지속으로 구현한다.

**Tech Stack:** 기존과 동일.

**스펙:** `docs/superpowers/specs/2026-08-05-pause-scrub-design.md`

## Global Constraints

- 코어(qt/ 밖) PySide6 금지, 이모지 금지 (ASCII와 한글만)
- 기본 인자/기존 시그니처 동작 불변 — 기존 85개 테스트 무수정 통과
- begin_scrub의 플레이어 조인은 락 밖에서 (조인 타임아웃 1.0초)
- SCRUBBING→PLAYING 직전환 (PASSTHROUGH 경유 금지 — 라이브 유출 창 없음)
- GUI 실행 금지, 임포트 체크 `py -3.11 -c "..."`, pytest 기존 인터프리터
- 커밋: 큰따옴표 금지, bash 작은따옴표, rtk 접두사, 한글 커밋 메시지

---

### Task 1: player 동적 구간 (set_range) + proxy.update_playback_range

**Files:**
- Modify: `arkit_recorder/player.py`
- Modify: `arkit_recorder/proxy.py`
- Test: `tests/test_player.py`, `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Produces:
  - `ClipPlayer.set_range(start_ms: int, end_ms: int | None) -> None`
  - play() 내부가 인스턴스 필드 `_range_start`/`_range_end`를 참조 (끝 경계는 매 프레임 동적 확인, 되감기는 현재 시작 기준 재계산)
  - `FaceProxy.update_playback_range(start_ms: int, end_ms: int | None) -> None` — PLAYING일 때만 위임

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_player.py`에 추가:

```python
def test_set_range_shrink_ends_playback(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate([0, 100, 200, 300])
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) == 2:
            player.set_range(0, 150)  # 재생 중 끝 축소

    player = make_player(clock, send)
    player.load(path)
    player.play()
    # t=200 프레임에서 150 초과 -> 즉시 종료
    assert [parse_packet(p).blendshapes["a"] for p in sent] == [0, 1]


def test_set_range_extend_continues(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate([0, 100, 200, 300])
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) == 1:
            player.set_range(0, 300)  # 재생 중 끝 확장

    player = make_player(clock, send)
    player.load(path)
    player.play(range_end_ms=100)
    assert [parse_packet(p).blendshapes["a"] for p in sent] == [0, 1, 2, 3]


def test_set_range_applies_to_loop_rewind(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate([0, 100, 200])
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) == 3:
            player.set_range(100, 200)  # 다음 되감기부터 구간 반영
        if len(sent) >= 5:
            player.stop()

    # 루프 크로스페이드를 끄고 되감기 반영만 검증
    player = make_player(clock, send, crossfade_loop_ms=0)
    player.load(path)
    player.play(loop=True)
    values = [parse_packet(p).blendshapes["a"] for p in sent]
    # 1바퀴 [0,1,2] -> 되감기(구간 100~200) [1,2] -> 5번째에서 정지
    assert values == [0, 1, 2, 1, 2]
```

`tests/test_proxy.py`에 추가:

```python
def test_update_playback_range_ignored_when_idle(proxy, warudo_socket):
    proxy.update_playback_range(0, 100)  # 비재생 -> 무시, 예외 없음


def test_update_playback_range_shrinks_live(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": i * 100, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate(range(10))
    ])
    proxy.start_playback(clip, loop=False)
    first = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert first == 0
    proxy.update_playback_range(0, 150)  # t<=150만 남김
    remaining = []
    warudo_socket.settimeout(1.0)
    try:
        while True:
            remaining.append(
                parse_packet(recv_text(warudo_socket)).blendshapes["a"]
            )
    except socket.timeout:
        pass
    assert all(v <= 1 for v in remaining)  # t=0,100 프레임(a-0/a-1)만
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_player.py tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`AttributeError: set_range`)

- [ ] **Step 3: 구현**

`player.py` — `__init__`에 추가:

```python
        self._range_start = 0
        self._range_end: int | None = None
```

`set_range` 추가:

```python
    def set_range(self, start_ms: int, end_ms: int | None) -> None:
        # 재생 중 구간 변경 (GUI 단일 작성자, int 대입은 GIL 원자적)
        self._range_start = start_ms
        self._range_end = end_ms
```

`play`를 다음으로 교체 (시그니처 동일, 내부가 동적 필드 참조):

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
        self._range_start = range_start_ms
        self._range_end = range_end_ms
        first_start = max(start_ms, range_start_ms)
        # 시작 경계만 선필터, 끝 경계는 매 프레임 동적 확인 (실시간 구간 반영)
        frames = (
            [(t, p) for t, p in self._frames if t >= first_start]
            if first_start > 0 else self._frames
        )
        if not self._has_playable(frames):
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            # base_ms 규칙: 바퀴 시작 경계가 0이면 base=0, 아니면 그 바퀴 첫 프레임 t
            base_ms = frames[0][0] if first_start > 0 else 0
            while not self._stop_event.is_set():
                start = self._now()
                for t_ms, packet in frames:
                    if self._stop_event.is_set():
                        return
                    end = self._range_end
                    if end is not None and t_ms > end:
                        break  # 현재 구간 끝 초과 — 바퀴 종료 (축소 즉시 반영)
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
                # 되감기: 현재 구간 시작 기준 재계산 (실시간 반영)
                rewind_start = self._range_start
                frames = (
                    [(t, p) for t, p in self._frames if t >= rewind_start]
                    if rewind_start > 0 else self._frames
                )
                if not self._has_playable(frames):
                    return
                base_ms = frames[0][0] if rewind_start > 0 else 0
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False

    def _has_playable(self, frames: list[tuple[int, str]]) -> bool:
        # 시작 필터된 목록의 첫 프레임이 현재 구간 끝 이내인가
        if not frames:
            return False
        end = self._range_end
        return end is None or frames[0][0] <= end
```

`proxy.py` — `playback_position_ms` 아래에 추가:

```python
    def update_playback_range(self, start_ms: int, end_ms: int | None) -> None:
        with self._mode_lock:
            if self._mode is not Mode.PLAYING:
                return
            player = self._player
        if player is not None:
            player.set_range(start_ms, end_ms)
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 85개 무수정)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/player.py arkit_recorder/proxy.py tests/test_player.py tests/test_proxy.py
rtk git commit -m 'feat: 재생 구간 실시간 변경'
```

---

### Task 2: proxy — 재생 중 스크럽 전환 / 일시정지 재개

**Files:**
- Modify: `arkit_recorder/proxy.py`
- Test: `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Produces:
  - `begin_scrub()` — PLAYING에서도 True (락: SCRUBBING 전환 → 락 해제 후 player.stop()+join(1.0))
  - `start_playback()` — SCRUBBING에서도 시작 허용 (리드인 = `_last_scrub_packet`), PASSTHROUGH 경유 없음
  - `_finish_playback` — 모드 복귀·페이드백 설정 모두 PLAYING 분기 안으로

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_proxy.py`에 추가)

```python
def test_begin_scrub_pauses_playback(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": i * 50, "d": f"a-{n}|trackingStatus-1|=|head#0,0,0|"}
        for n, i in enumerate(range(100))
    ])
    proxy.start_playback(clip, loop=True)
    recv_text(warudo_socket)  # 재생 확인
    assert proxy.begin_scrub() is True  # 재생 중 스크럽 -> 일시정지 전환
    assert proxy.mode is Mode.SCRUBBING
    # 조인 완료 후이므로 잔여 재생 프레임을 비우고 나면 조용해야 함
    warudo_socket.settimeout(0.3)
    try:
        while True:
            warudo_socket.recvfrom(65535)
    except socket.timeout:
        pass
    proxy.scrub_frame(SCRUB_A)
    warudo_socket.settimeout(2.0)
    assert parse_packet(recv_text(warudo_socket)).blendshapes["a"] == 10
    proxy.end_scrub()
    assert proxy.mode is Mode.PASSTHROUGH


def test_start_playback_resumes_from_scrub(proxy, warudo_socket):
    assert proxy.begin_scrub() is True
    proxy.scrub_frame("a-0|trackingStatus-1|=|head#0,0,0|")
    recv_text(warudo_socket)
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-100|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-100|trackingStatus-1|=|head#0,0,0|"},
    ])
    count = proxy.start_playback(clip, loop=False)  # SCRUBBING에서 직전환
    assert count == 2
    values = [
        parse_packet(recv_text(warudo_socket)).blendshapes["a"] for _ in range(2)
    ]
    # 리드인이 마지막 스크럽 프레임(a=0): fixture fade 2000ms
    # t=0 -> blend(0,100,0)=0, t=100 -> blend(0,100,0.05)=5
    assert values == [0, 5]
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: 새 테스트 FAIL (begin_scrub이 PLAYING에서 False / start_playback이 SCRUBBING에서 0)

- [ ] **Step 3: 구현**

`begin_scrub`을 다음으로 교체:

```python
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
```

`_finish_playback`을 다음으로 교체 (페이드백 설정을 PLAYING 분기 안으로):

```python
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
```

`start_playback`의 락 블록 시작부를 다음으로 교체 (나머지 본문 유지):

```python
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
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 스크럽/페이드백 테스트 무수정)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/proxy.py tests/test_proxy.py
rtk git commit -m 'feat: 재생 중 스크럽 전환과 일시정지 재개'
```

---

### Task 3: GUI — QSS 체크 표시 + 위젯 paused 상태 + 메인 윈도우 배선

**Files:**
- Modify: `arkit_recorder/qt/app.py` (QSS 한 줄)
- Modify: `arkit_recorder/qt/timeline_widget.py` (paused 상태 머신)
- Modify: `arkit_recorder/qt/main_window.py` (재생/정지/poll/클립 선택 배선)

**Interfaces:**
- Consumes: Task 1 `update_playback_range`, Task 2 begin_scrub/start_playback 확장
- Produces: `TimelineWidget.is_paused() -> bool`, `release_pause(end: bool) -> None`

- [ ] **Step 1: app.py QSS** — DARK_QSS의 `QPushButton:disabled` 줄 다음에 추가:

```
QPushButton:checked { background-color: #3d5a80; border-color: #4f9cf9; }
```

- [ ] **Step 2: timeline_widget.py**

import에 추가: `from ..proxy import Mode`

`__init__`에 추가 (`_last_scrub_index` 아래):

```python
        self._paused = False
        self._scrub_from_playing = False
```

공개 API 추가 (`is_live` 아래):

```python
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
```

`mousePressEvent`의 스크럽 시작 분기를 다음으로 교체:

```python
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
```

`mouseReleaseEvent`를 다음으로 교체:

```python
    def mouseReleaseEvent(self, event) -> None:
        if self._dragging == "scrub":
            if self._paused or self._scrub_from_playing:
                # 재생 중 시작한 스크럽 -> 일시정지 유지 (킵얼라이브 계속 = 프레임 고정)
                self._paused = True
            else:
                self._keepalive.stop()
                self._proxy.end_scrub()
        self._dragging = None
```

`_resend_scrub`의 첫 가드를 다음으로 교체:

```python
        if not (self._dragging == "scrub" or self._paused):
            return
        if self._data is None:
            return
```

- [ ] **Step 3: main_window.py**

`_on_play`를 다음으로 교체:

```python
    def _on_play(self) -> None:
        mode = self._proxy.mode
        paused = self._timeline.is_paused()
        if mode is Mode.PLAYING or (mode is Mode.SCRUBBING and not paused):
            return
        info = self._selected_info()
        if info is None:
            return
        if paused:
            self._timeline.release_pause(end=False)  # 재개 — start_playback이 직전환
        start_ms, range_start, range_end = self._playback_range()
        count = self._proxy.start_playback(
            info.path, self._loop_button.isChecked(),
            start_ms=start_ms, range_start_ms=range_start, range_end_ms=range_end,
        )
        if count == 0:
            if paused:
                self._proxy.end_scrub()  # 재개 실패 — 일시정지 완전 해제
            QMessageBox.warning(
                self, "재생", "클립을 재생할 수 없습니다 (빈 파일 또는 녹화 중)."
            )
```

`_on_stop`을 다음으로 교체:

```python
    def _on_stop(self) -> None:
        if self._timeline.is_paused():
            self._timeline.release_pause(end=True)  # 일시정지 해제 -> 라이브 복귀
            return
        self._stopped_by_user = True  # 정지 버튼: 플레이헤드 유지 (스펙 §4.3)
        self._proxy.stop_playback()
```

`_on_clip_selected` 맨 앞(빈 row 분기보다 먼저)에 추가:

```python
        if self._timeline.is_paused():
            self._timeline.release_pause(end=True)  # 이전 클립 프레임 고정 해제
```

`_poll`의 모드 라벨/버튼 상태 부분을 다음으로 교체 (전이 블록·수신 라벨은 유지):

```python
        paused = self._timeline.is_paused()
        if paused:
            self._mode_label.setText("모드: 일시정지")
        else:
            self._mode_label.setText(f"모드: {MODE_NAMES[mode]}")
        self._forward_label.setText(
            f"전달: {self._config.forward_host}:{self._config.forward_port}"
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
        self._stop_button.setEnabled(mode is Mode.PLAYING or paused)
        self._play_button.setEnabled(not busy)
        self._record_button.setEnabled(not busy and not paused)
        self._rename_button.setEnabled(not busy and not paused)
        self._delete_button.setEnabled(not busy and not paused)
```

트림 마커의 실시간 반영 — `mouseMoveEvent`는 timeline_widget에 있으므로 위젯 쪽에서 처리:
`timeline_widget.py`의 `mouseMoveEvent` trim 분기 두 곳 각각의 `self.update()` 앞에 추가:

```python
            self._proxy.update_playback_range(self._trim_start, self._trim_end)
```

(비재생 중에는 proxy가 무시하므로 무조건 호출해도 안전)

- [ ] **Step 4: 검증**

```
python -m pytest tests/ -v      → 전부 PASS
py -3.11 -c "import arkit_recorder.qt.app; import arkit_recorder.qt.main_window; import arkit_recorder.qt.timeline_widget; print('import ok')"
```

GUI 실행 금지.

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/qt
rtk git commit -m 'feat: 루프 체크 표시, 실시간 구간 배선, 일시정지 스크럽'
```

---

## 수동 스모크 (구현 완료 후, 사용자 진행)

1. 루프 버튼 토글 시 색 변화
2. 루프 재생 중 트림 마커 이동 → 즉시 구간 반영
3. 재생 중 타임라인 잡기 → 일시정지+탐색, 놓으면 그 표정 고정 (0.5초 후에도 유지)
4. 일시정지에서 [재생] → 그 위치부터 재개, [정지] → 라이브 복귀
5. 일시정지 중 다른 클립 선택 → 고정 해제 후 새 클립 로드
