# v2.3 일시정지 상태 버튼 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 컨트롤 바를 [재생] [일시정지(체크형)] [정지] [루프]로 재구성하고, 일시정지 상태를 버튼으로 표시·조작한다.

**Architecture:** 코어 무변경. 위젯에 pause_at_playhead 진입 메서드 하나, 메인 윈도우에 버튼과 핸들러/폴 동기화.

**스펙:** `docs/superpowers/specs/2026-08-05-pause-button-design.md`

## Global Constraints

- 코어(qt/ 밖) 무변경, 기존 92개 테스트 무수정 통과
- 이모지 금지 (Qt 표준 아이콘 OK), GUI 실행 금지
- 커밋: 큰따옴표 금지, bash 작은따옴표, rtk 접두사, 한글 커밋 메시지

---

### Task 1: 일시정지 상태 버튼

**Files:**
- Modify: `arkit_recorder/qt/timeline_widget.py` (pause_at_playhead 추가)
- Modify: `arkit_recorder/qt/main_window.py` (버튼/핸들러/폴)

**Interfaces:**
- Produces: `TimelineWidget.pause_at_playhead() -> bool`

- [ ] **Step 1: timeline_widget.py** — `release_pause` 아래에 추가:

```python
    def pause_at_playhead(self) -> bool:
        # 재생 중 현재 위치에서 일시정지 (버튼용) — 스크럽 일시정지와 동일 상태로 진입
        if self._data is None or not self._data.frames:
            return False
        if not self._proxy.begin_scrub():
            return False
        index = frame_index_at(self._data, self._playhead_ms)
        if index < 0:
            index = 0
        self._last_scrub_index = index
        t_ms, packet = self._data.frames[index]
        self._proxy.scrub_frame(packet)
        self._playhead_ms = t_ms
        self._paused = True
        self._keepalive.start()
        self.update()
        return True
```

- [ ] **Step 2: main_window.py 컨트롤 바** — `_build_ui`의 컨트롤 바 블록에서 버튼 생성/배치를 다음 순서로 교체 ([재생] [일시정지] [정지] [루프]):

```python
        controls = QHBoxLayout()
        controls.addStretch(1)
        style = self.style()
        self._play_button = QPushButton("재생")
        self._play_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self._play_button.clicked.connect(self._on_play)
        self._pause_button = QPushButton("일시정지")
        self._pause_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        )
        self._pause_button.setCheckable(True)
        self._pause_button.setEnabled(False)
        self._pause_button.clicked.connect(self._on_pause)
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
        controls.addWidget(self._pause_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._loop_button)
        controls.addStretch(1)
        self._right_panel.addLayout(controls)
```

- [ ] **Step 3: 핸들러 추가** (`_on_stop` 위):

```python
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
```

- [ ] **Step 4: 폴 동기화** — `_poll`의 `self._stop_button.setEnabled(...)` 줄 앞에 추가:

```python
        # clicked는 사용자 클릭에만 발화하므로 setChecked와 충돌 없음
        self._pause_button.setChecked(paused)
        self._pause_button.setEnabled(mode is Mode.PLAYING or paused)
```

- [ ] **Step 5: 검증**

```
python -m pytest tests/ -v      → 92개 전부 PASS (코어 무변경)
py -3.11 -c "import arkit_recorder.qt.main_window; import arkit_recorder.qt.timeline_widget; print('import ok')"
```

- [ ] **Step 6: 커밋**

```bash
rtk git add arkit_recorder/qt
rtk git commit -m 'feat: 일시정지 상태 버튼'
```

---

### Task 2: 스크럽 릴리즈 = 항상 일시정지

(추가 피드백: 타임라인 클릭 시 해당 프레임으로 이동하며 일시정지 모드로. 라이브 복귀는 [정지]로 일원화)

**Files:**
- Modify: `arkit_recorder/qt/timeline_widget.py`

- [ ] **Step 1: mouseReleaseEvent 교체**

```python
    def mouseReleaseEvent(self, event) -> None:
        if self._dragging == "scrub":
            # 스크럽을 놓으면 항상 일시정지 유지 (킵얼라이브 계속 = 프레임 고정)
            # 라이브 복귀는 [정지] 버튼으로
            self._paused = True
        self._dragging = None
```

- [ ] **Step 2: mousePressEvent 스크럽 분기 단순화** — `_scrub_from_playing` 관련 제거:

```python
        if self._paused:
            # 일시정지 중 재탐색 — 이미 SCRUBBING 모드, begin_scrub 불필요
            self._dragging = "scrub"
            self._scrub_to(x)
            return
        if self._proxy.begin_scrub():
            self._dragging = "scrub"
            self._last_scrub_index = -1
            self._keepalive.start()
            self._scrub_to(x)
```

- [ ] **Step 3: 잔재 제거** — `__init__`의 `self._scrub_from_playing = False`, `release_pause`의 `self._scrub_from_playing = False` 줄 삭제. `from ..proxy import Mode` import가 위젯에서 미사용이 되면 제거 (pause_at_playhead는 Mode 미사용 — grep으로 확인).

- [ ] **Step 4: 검증** — `python -m pytest tests/ -v` (92개) + `py -3.11 -c "import arkit_recorder.qt.timeline_widget; print('import ok')"`

- [ ] **Step 5: 커밋** — `rtk git add arkit_recorder/qt/timeline_widget.py && rtk git commit -m '피처: 스크럽 릴리즈를 항상 일시정지로'` (한글 메시지: `feat: 스크럽 릴리즈를 항상 일시정지로`)

## 수동 스모크 (사용자)

1. 재생 중 [일시정지] → 현재 프레임 고정(체크 표시), 다시 클릭 → 그 위치부터 재개
2. 타임라인 클릭/스크럽 (라이브·재생 무관) → 놓으면 해당 프레임 고정 + [일시정지] 자동 체크
3. 일시정지 중 [정지] → 라이브 복귀 + 체크 해제
4. 비재생 상태에서 [일시정지] 클릭 → 무동작 (체크 안 됨, 버튼 비활성)
