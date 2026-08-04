# Qt UI 현대화 + 타임라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tkinter GUI를 PySide6 다크 대시보드로 교체하고, 곡선 시각화·스크러빙·트리밍·녹화 실시간 표시를 갖춘 클립 타임라인을 추가한다.

**Architecture:** 코어(protocol/proxy/recorder/player/clips/config)는 최소 확장만 하고 PySide6 미의존을 유지한다. 타임라인 데이터는 순수 로직 모듈 `timeline.py`로 분리해 pytest로 검증하고, Qt 위젯(`arkit_recorder/qt/`)은 QTimer 폴링으로 코어를 관찰하는 얇은 배선이다. 스크럽은 proxy의 새 SCRUBBING 모드로 라이브를 차단하고 프레임을 1회씩 송출한다.

**Tech Stack:** Python 3.11, PySide6>=6.6 (유일한 신규 의존성), pytest 9 (코어 전용).

**스펙:** `docs/superpowers/specs/2026-08-05-qt-ui-timeline-design.md` (모든 수치·규칙의 원본)

## Global Constraints

- 신규 의존성은 PySide6만. `arkit_recorder/qt/` 밖의 모듈은 PySide6를 import하지 않는다 (코어 테스트는 PySide6 없이 실행 가능해야 함)
- PySide6 설치/임포트 검증은 시스템 Python 사용: `py -3.11 -m pip install "PySide6>=6.6"`, 임포트 체크는 `py -3.11 -c "..."`. pytest는 기존 인터프리터(`python -m pytest tests/ -v`) 그대로
- 기존 54개 테스트 회귀 없음 필수
- GUI 실행 금지 (`python main.py`, `py -3.11 main.py` 금지) — 임포트 체크와 pytest로만 검증
- 이모지 금지 (ASCII와 한글만, — em dash 허용), UI 문자열은 한글
- 활동량 = 두 프레임 모두에 있는 블렌드쉐이프 키의 값 차 절대값 합, trackingStatus 제외. 파싱 불가 프레임의 활동량은 0.0
- 스크럽: 프레임 인덱스가 바뀐 경우에만 송출, trackingStatus-0 프레임은 송출 생략
- 트리밍은 비파괴 (원본 유지, 새 클립 저장), t는 0 기준 재정렬
- 커밋: 큰따옴표 금지, bash 작은따옴표, rtk 접두사, 한글 커밋 메시지

## 파일 구조 (전체)

```
requirements.txt                신설: PySide6>=6.6 (Task 6)
main.py                         qt 앱 실행으로 변경 (Task 6)
arkit_recorder/
  timeline.py                   신설: 타임라인 데이터 순수 로직 (Task 1)
  clips.py                      validate_clip_name 추출 (Task 2)
  player.py                     position_ms, start_ms (Task 3)
  proxy.py                      start_playback(start_ms), playback_position_ms (Task 3)
                                + Mode.SCRUBBING, begin/scrub_frame/end_scrub (Task 5)
  recorder.py                   활동량 링버퍼 live_wave (Task 4)
  gui.py                        삭제 (Task 6)
  settings_dialog.py            삭제 (Task 6)
  qt/
    __init__.py                 신설 빈 파일 (Task 6)
    app.py                      신설: QApplication+다크 QSS+run_app (Task 6)
    settings_dialog.py          신설: Qt판 설정 다이얼로그 (Task 6)
    main_window.py              신설: 대시보드 (Task 6, Task 7에서 타임라인 배선)
    timeline_widget.py          신설: QPainter 타임라인 (Task 7)
tests/
  test_timeline.py              신설 (Task 1)
  test_clips.py                 validate 테스트 추가 (Task 2)
  test_player.py                position/start_ms 테스트 추가 (Task 3)
  test_recorder.py              링버퍼 테스트 추가 (Task 4)
  test_proxy.py                 스크럽 테스트 추가 (Task 5)
```

---

### Task 1: timeline.py — 타임라인 데이터 순수 로직

**Files:**
- Create: `arkit_recorder/timeline.py`
- Test: `tests/test_timeline.py`

**Interfaces:**
- Consumes: `protocol.parse_packet`, `protocol.Frame`
- Produces:
  - `TimelineData` dataclass: `frames: list[tuple[int, str]]`, `duration_ms: int`
  - `load_timeline(path: Path) -> TimelineData` — 손상 라인 스킵 (ClipPlayer.load와 동일 규칙)
  - `frame_activity(prev: Frame | None, curr: Frame | None) -> float` — 공통 키(trackingStatus 제외) 값 차 절대값 합
  - `activity_curve(data: TimelineData) -> list[tuple[int, float]]` — 프레임별 (t_ms, 활동량), 0번째는 0.0
  - `blendshape_curve(data: TimelineData, name: str) -> list[tuple[int, int]]` — 해당 키 없는/파싱 불가 프레임 건너뜀
  - `blendshape_names(data: TimelineData) -> list[str]` — 전 프레임 키 합집합 정렬, trackingStatus 제외
  - `frame_index_at(data: TimelineData, t_ms: int) -> int` — t_ms 이하 최근접 인덱스(이진 탐색), 빈 클립 -1, t_ms가 첫 프레임보다 작으면 0
  - `trim(data: TimelineData, start_ms: int, end_ms: int) -> list[tuple[int, str]]` — 구간 프레임을 t=0 기준 재정렬
  - `save_frames(frames: list[tuple[int, str]], path: Path) -> int` — JSONL 저장, 프레임 수 반환

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_timeline.py
import json

import pytest

from arkit_recorder.protocol import parse_packet
from arkit_recorder.timeline import (
    TimelineData,
    activity_curve,
    blendshape_curve,
    blendshape_names,
    frame_activity,
    frame_index_at,
    load_timeline,
    save_frames,
    trim,
)


def P(**shapes):
    body = "|".join(f"{k}-{v}" for k, v in shapes.items())
    return body + "|trackingStatus-1|=|head#0,0,0|"


def write_clip(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )


def make_data(pairs):
    return TimelineData(frames=list(pairs), duration_ms=pairs[-1][0] if pairs else 0)


def test_load_timeline_skips_corrupt(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(
        '{"t": 0, "d": "a-1|=|head#0,0,0|"}\n'
        "garbage\n"
        '{"t": 100, "d": "a-2|=|head#0,0,0|"}\n',
        encoding="utf-8",
    )
    data = load_timeline(path)
    assert len(data.frames) == 2
    assert data.duration_ms == 100


def test_load_timeline_empty(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text("", encoding="utf-8")
    data = load_timeline(path)
    assert data.frames == []
    assert data.duration_ms == 0


def test_frame_activity_common_keys_only():
    a = parse_packet(P(jawOpen=10, smile=50, onlyA=99))
    b = parse_packet(P(jawOpen=30, smile=45, onlyB=77))
    # 공통 키: jawOpen |30-10|=20, smile |45-50|=5 -> 25. trackingStatus/단독 키 제외
    assert frame_activity(a, b) == pytest.approx(25.0)
    assert frame_activity(None, b) == 0.0
    assert frame_activity(a, None) == 0.0


def test_activity_curve():
    data = make_data([
        (0, P(jawOpen=0)),
        (100, P(jawOpen=40)),
        (200, "not parseable"),
        (300, P(jawOpen=100)),
    ])
    curve = activity_curve(data)
    assert curve[0] == (0, 0.0)
    assert curve[1] == (100, pytest.approx(40.0))
    assert curve[2] == (200, 0.0)              # 파싱 불가 -> 0.0
    assert curve[3] == (300, pytest.approx(60.0))  # 직전 유효 프레임(t=100) 대비


def test_blendshape_curve_and_names():
    data = make_data([
        (0, P(jawOpen=1, smile=2)),
        (50, "broken"),
        (100, P(jawOpen=3)),
    ])
    assert blendshape_curve(data, "jawOpen") == [(0, 1), (100, 3)]
    assert blendshape_curve(data, "smile") == [(0, 2)]
    assert blendshape_names(data) == ["jawOpen", "smile"]  # trackingStatus 제외, 정렬


def test_frame_index_at():
    data = make_data([(0, "x"), (100, "y"), (250, "z")])
    assert frame_index_at(data, -5) == 0
    assert frame_index_at(data, 0) == 0
    assert frame_index_at(data, 99) == 0
    assert frame_index_at(data, 100) == 1
    assert frame_index_at(data, 260) == 2
    assert frame_index_at(TimelineData(frames=[], duration_ms=0), 50) == -1


def test_trim_rebases_time():
    data = make_data([(0, "a"), (100, "b"), (200, "c"), (300, "d")])
    out = trim(data, 100, 200)
    assert out == [(0, "b"), (100, "c")]
    assert trim(data, 250, 260) == []
    assert trim(data, 0, 300) == [(0, "a"), (100, "b"), (200, "c"), (300, "d")]


def test_save_frames_roundtrip(tmp_path):
    path = tmp_path / "out.jsonl"
    frames = [(0, "a-1|=|head#0,0,0|"), (100, "a-2|=|head#0,0,0|")]
    assert save_frames(frames, path) == 2
    data = load_timeline(path)
    assert data.frames == frames
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_timeline.py -v`
예상: 전부 FAIL (`ModuleNotFoundError: arkit_recorder.timeline`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/timeline.py
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import Frame, parse_packet


@dataclass
class TimelineData:
    frames: list[tuple[int, str]] = field(default_factory=list)
    duration_ms: int = 0


def load_timeline(path: Path) -> TimelineData:
    frames: list[tuple[int, str]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                frames.append((int(entry["t"]), str(entry["d"])))
            except (ValueError, KeyError, TypeError):
                continue  # 손상 라인 스킵 (ClipPlayer.load와 동일 규칙)
    duration = frames[-1][0] if frames else 0
    return TimelineData(frames=frames, duration_ms=duration)


def frame_activity(prev: Frame | None, curr: Frame | None) -> float:
    # 두 프레임 모두에 있는 키만 합산. trackingStatus 제외.
    if prev is None or curr is None:
        return 0.0
    total = 0.0
    for name, value in curr.blendshapes.items():
        if name == "trackingStatus":
            continue
        prev_value = prev.blendshapes.get(name)
        if prev_value is not None:
            total += abs(value - prev_value)
    return total


def activity_curve(data: TimelineData) -> list[tuple[int, float]]:
    curve: list[tuple[int, float]] = []
    prev: Frame | None = None
    for t_ms, packet in data.frames:
        frame = parse_packet(packet)
        if frame is None:
            curve.append((t_ms, 0.0))
            continue  # prev는 마지막 유효 프레임 유지
        curve.append((t_ms, frame_activity(prev, frame)))
        prev = frame
    return curve


def blendshape_curve(data: TimelineData, name: str) -> list[tuple[int, int]]:
    curve: list[tuple[int, int]] = []
    for t_ms, packet in data.frames:
        frame = parse_packet(packet)
        if frame is None:
            continue
        value = frame.blendshapes.get(name)
        if value is not None:
            curve.append((t_ms, value))
    return curve


def blendshape_names(data: TimelineData) -> list[str]:
    names: set[str] = set()
    for _, packet in data.frames:
        frame = parse_packet(packet)
        if frame is not None:
            names.update(frame.blendshapes)
    names.discard("trackingStatus")
    return sorted(names)


def frame_index_at(data: TimelineData, t_ms: int) -> int:
    if not data.frames:
        return -1
    times = [t for t, _ in data.frames]
    index = bisect_right(times, t_ms) - 1
    return max(0, index)


def trim(data: TimelineData, start_ms: int, end_ms: int) -> list[tuple[int, str]]:
    selected = [(t, p) for t, p in data.frames if start_ms <= t <= end_ms]
    if not selected:
        return []
    base = selected[0][0]
    return [(t - base, p) for t, p in selected]


def save_frames(frames: list[tuple[int, str]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for t_ms, packet in frames:
            f.write(json.dumps({"t": t_ms, "d": packet}) + "\n")
    return len(frames)
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_timeline.py -v` → 전부 PASS
전체 1회: `python -m pytest tests/ -v` → 회귀 없음

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/timeline.py tests/test_timeline.py
rtk git commit -m 'feat: 타임라인 데이터 순수 로직 모듈'
```

---

### Task 2: clips.validate_clip_name 추출

**Files:**
- Modify: `arkit_recorder/clips.py`
- Test: `tests/test_clips.py` (테스트 추가)

**Interfaces:**
- Consumes: 기존 `rename_clip`
- Produces:
  - `validate_clip_name(clips_dir: Path, name: str) -> Path` — strip 후 빈 이름/밑줄 시작/경로 문자(`/`, `\`, `..`)/중복 검사, 위반 시 기존과 동일한 한글 ValueError, 통과 시 `clips_dir/이름.jsonl` 경로 반환
  - `rename_clip`은 이 헬퍼를 재사용 (동작 불변 — 기존 테스트가 그대로 통과해야 함)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_clips.py`에 추가)

```python
from arkit_recorder.clips import validate_clip_name


def test_validate_clip_name_ok(tmp_path):
    assert validate_clip_name(tmp_path, "  fine  ") == tmp_path / "fine.jsonl"


def test_validate_clip_name_errors(tmp_path):
    write_clip(tmp_path, "taken", [{"t": 0, "d": "x"}])
    with pytest.raises(ValueError):
        validate_clip_name(tmp_path, "")
    with pytest.raises(ValueError):
        validate_clip_name(tmp_path, "_hidden")
    with pytest.raises(ValueError):
        validate_clip_name(tmp_path, "a/b")
    with pytest.raises(ValueError):
        validate_clip_name(tmp_path, "taken")
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_clips.py -v`
예상: 새 테스트만 FAIL (`ImportError: validate_clip_name`)

- [ ] **Step 3: 구현** — `clips.py`의 `rename_clip`을 다음으로 교체 (검증부를 헬퍼로 추출, 메시지·순서 불변):

```python
def validate_clip_name(clips_dir: Path, name: str) -> Path:
    name = name.strip()
    if not name:
        raise ValueError("클립 이름이 비어 있습니다")
    if name.startswith("_"):
        raise ValueError("밑줄로 시작하는 이름은 사용할 수 없습니다")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("이름에 경로 문자를 사용할 수 없습니다")
    path = clips_dir / (name + ".jsonl")
    if path.exists():
        raise ValueError(f"같은 이름의 클립이 이미 있습니다: {name}")
    return path


def rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path:
    new_path = validate_clip_name(clips_dir, new_name)
    old_path = clips_dir / (old_name + ".jsonl")
    if not old_path.exists():
        raise ValueError(f"클립을 찾을 수 없습니다: {old_name}")
    old_path.rename(new_path)
    return new_path
```

주의: 기존 rename_clip은 "원본 없음" 검사가 "중복" 검사보다 뒤였다 — 이 순서를
유지해야 기존 테스트(`ghost` -> `new` 케이스)가 통과한다. 위 코드는 검증 헬퍼가
중복까지 검사한 뒤 원본 존재를 확인하므로 순서가 동일하다.

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_clips.py -v` → 전부 PASS (기존 포함)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/clips.py tests/test_clips.py
rtk git commit -m 'refactor: 클립 이름 검증 헬퍼 추출'
```

---

### Task 3: player position_ms / start_ms + proxy 전달

**Files:**
- Modify: `arkit_recorder/player.py`
- Modify: `arkit_recorder/proxy.py` (start_playback에 start_ms, playback_position_ms 추가)
- Test: `tests/test_player.py`, `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Consumes: 기존 `ClipPlayer`, `FaceProxy`
- Produces:
  - `ClipPlayer.position_ms: int` — 마지막 송출 프레임의 클립 내 절대 t_ms (초기 0)
  - `ClipPlayer.play(loop=False, lead_in_packet=None, start_ms=0)` — start_ms 이상 첫 프레임부터, 타이밍·리드인 페이드는 `t_ms - start_ms` 기준. 루프 되감기는 항상 0부터 (기존 동작)
  - `FaceProxy.start_playback(clip_path, loop, start_ms=0) -> int`
  - `FaceProxy.playback_position_ms() -> int | None` — PLAYING이면 position_ms, 아니면 None

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_player.py`에 추가:

```python
def test_start_ms_skips_and_rebases_timing(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
        {"t": 250, "d": "a-3|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append((clock.time, p)))
    player.load(path)
    player.play(start_ms=100)
    # t=100 프레임이 즉시(0.0초), t=250 프레임이 0.15초에 송출
    assert [t for t, _ in sent] == [0.0, pytest.approx(0.15)]
    assert [parse_packet(p).blendshapes["a"] for _, p in sent] == [2, 3]
    assert player.position_ms == 250


def test_position_ms_tracks_playback(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    positions = []
    player = make_player(clock, lambda p: positions.append(player.position_ms))
    player.load(path)
    player.play()
    # 콜백 시점에는 직전 프레임 위치, 종료 후 마지막 프레임 위치
    assert player.position_ms == 100


def test_start_ms_loop_rewinds_to_zero(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 50, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) >= 3:
            player.stop()

    player = make_player(clock, send)
    player.load(path)
    player.play(loop=True, start_ms=50)
    values = [parse_packet(p).blendshapes["a"] for p in sent]
    # 1바퀴: start_ms=50부터 [2], 2바퀴: 처음(0)부터 [1, 2...]
    assert values[0] == 2
    assert values[1] == 1


def test_start_ms_beyond_clip_sends_nothing(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [{"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"}])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p))
    player.load(path)
    player.play(start_ms=999)
    assert sent == []
    assert not player.is_playing
```

`tests/test_proxy.py`에 추가:

```python
def test_playback_position_and_start_ms(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 50, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    assert proxy.playback_position_ms() is None  # 재생 전
    count = proxy.start_playback(clip, loop=False, start_ms=50)
    assert count == 2  # 반환값은 전체 로드 프레임 수 (기존 의미 유지)
    value = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert value == 2  # start_ms=50부터이므로 첫 송출이 a-2
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
    assert proxy.playback_position_ms() is None  # 종료 후
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_player.py tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`TypeError: play() got an unexpected keyword argument`)

- [ ] **Step 3: 구현**

`player.py` — `__init__`에 `self.position_ms = 0` 추가, `play`를 다음으로 교체:

```python
    def play(
        self,
        loop: bool = False,
        lead_in_packet: str | None = None,
        start_ms: int = 0,
    ) -> None:
        # 블로킹 — 호출자는 별도 스레드에서 실행한다
        if self.is_playing:
            return
        first_frames = (
            [(t, p) for t, p in self._frames if t >= start_ms]
            if start_ms > 0 else self._frames
        )
        if not first_frames:
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            frames = first_frames
            base_ms = first_frames[0][0] if start_ms > 0 else 0
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
                # 루프 되감기는 항상 클립 전체(0부터)
                frames = self._frames
                base_ms = 0
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False
```

주의: `_prepare`에는 상대 시각 `rel_ms`를 넘긴다 — 리드인/루프 크로스페이드의
진행 기준이 재생 시작 시점부터가 되도록. `_prepare` 자체는 무변경.
`position_ms`에는 클립 내 절대 t_ms를 기록한다 (플레이헤드 표시용).

`proxy.py` — `start_playback` 시그니처를 `(self, clip_path, loop, start_ms=0)`으로
바꾸고, `_run_player`에 start_ms를 전달:

```python
    def start_playback(self, clip_path: Path, loop: bool, start_ms: int = 0) -> int:
        # (기존 본문 동일, 마지막 스레드 생성부만)
        self._player_thread = threading.Thread(
            target=self._run_player, args=(player, loop, lead_in, start_ms), daemon=True
        )

    def _run_player(
        self, player: ClipPlayer, loop: bool, lead_in: str | None, start_ms: int = 0
    ) -> None:
        try:
            player.play(loop=loop, lead_in_packet=lead_in, start_ms=start_ms)
        finally:
            self._finish_playback(player)

    def playback_position_ms(self) -> int | None:
        player = self._player
        if self.mode is Mode.PLAYING and player is not None:
            return player.position_ms
        return None
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS (기존 포함, 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/player.py arkit_recorder/proxy.py tests/test_player.py tests/test_proxy.py
rtk git commit -m 'feat: 재생 위치 추적과 시작 오프셋'
```

---

### Task 4: recorder 활동량 링버퍼

**Files:**
- Modify: `arkit_recorder/recorder.py`
- Test: `tests/test_recorder.py` (테스트 추가)

**Interfaces:**
- Consumes: `timeline.frame_activity`, `protocol.parse_packet`
- Produces:
  - `ClipRecorder.live_wave() -> list[tuple[int, float]]` — (t_ms, 활동량) 스냅샷. `start()` 시 초기화. 버퍼는 `deque(maxlen=36000)` (60fps 10분)

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_recorder.py`에 추가)

```python
def test_live_wave_accumulates_activity(tmp_path):
    clock = FakeClock()
    rec = ClipRecorder(tmp_path / "_tmp.jsonl", now=clock.now)
    rec.start()
    rec.feed("jawOpen-0|trackingStatus-1|=|head#0,0,0|")
    clock.time += 0.1
    rec.feed("jawOpen-40|trackingStatus-1|=|head#0,0,0|")
    clock.time += 0.1
    rec.feed("not parseable")
    wave = rec.live_wave()
    assert wave[0] == (0, 0.0)          # 첫 프레임 활동량 0
    assert wave[1] == (100, 40.0)       # |40-0|
    assert wave[2] == (200, 0.0)        # 파싱 불가 -> 0.0
    rec.stop_and_save(tmp_path / "c.jsonl")


def test_live_wave_resets_on_start(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.start()
    rec.feed("a-1|trackingStatus-1|=|head#0,0,0|")
    rec.stop_and_save(tmp_path / "one.jsonl")
    rec.start()
    assert rec.live_wave() == []
    rec.discard()
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_recorder.py -v`
예상: 새 테스트만 FAIL (`AttributeError: live_wave`)

- [ ] **Step 3: 구현** — `recorder.py` 수정:

상단 import 추가:

```python
from collections import deque

from .protocol import Frame, parse_packet
from .timeline import frame_activity
```

`__init__`에 추가:

```python
        self._wave: deque[tuple[int, float]] = deque(maxlen=36000)  # 60fps 10분
        self._prev_frame: Frame | None = None
```

`start()`의 락 블록 안 (frame_count 리셋 옆)에 추가:

```python
            self._wave.clear()
            self._prev_frame = None
```

`feed()`의 락 블록 안, 파일 쓰기 다음에 추가:

```python
            frame = parse_packet(packet)
            if frame is None:
                self._wave.append((t_ms, 0.0))
            else:
                self._wave.append((t_ms, frame_activity(self._prev_frame, frame)))
                self._prev_frame = frame
```

메서드 추가:

```python
    def live_wave(self) -> list[tuple[int, float]]:
        with self._lock:
            return list(self._wave)
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/recorder.py tests/test_recorder.py
rtk git commit -m 'feat: 녹화 실시간 활동량 링버퍼'
```

---

### Task 5: proxy 스크럽 (Mode.SCRUBBING)

**Files:**
- Modify: `arkit_recorder/proxy.py`
- Test: `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Consumes: 기존 FaceProxy 내부 (_forward, _fade_back_from 메커니즘, live_available)
- Produces:
  - `Mode.SCRUBBING`
  - `begin_scrub() -> bool` — PASSTHROUGH에서만 True(전환), 아니면 False
  - `scrub_frame(packet: str) -> None` — SCRUBBING에서만 송출, trackingStatus-0 생략
  - `end_scrub() -> None` — PASSTHROUGH 복귀 + 라이브 가용 시 페이드백 준비
  - `_recv_loop`의 라이브 차단이 PLAYING과 SCRUBBING 모두에 적용

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_proxy.py`에 추가)

```python
SCRUB_A = "a-10|trackingStatus-1|=|head#0,0,0|"
SCRUB_B = "a-90|trackingStatus-1|=|head#0,0,0|"


def test_scrub_forwards_and_blocks_live(proxy, warudo_socket):
    assert proxy.begin_scrub() is True
    assert proxy.mode is Mode.SCRUBBING
    assert proxy.begin_scrub() is False  # 중복 시작 불가
    send_to_proxy(proxy, "live-99|trackingStatus-1|=|head#0,0,0|")  # 차단
    proxy.scrub_frame(SCRUB_A)
    proxy.scrub_frame("skip-1|trackingStatus-0|=|head#0,0,0|")  # 생략
    proxy.scrub_frame(SCRUB_B)
    received = [recv_text(warudo_socket), recv_text(warudo_socket)]
    assert [parse_packet(p).blendshapes["a"] for p in received] == [10, 90]
    proxy.end_scrub()
    assert proxy.mode is Mode.PASSTHROUGH
    warudo_socket.settimeout(0.3)
    with pytest.raises(socket.timeout):
        warudo_socket.recvfrom(65535)  # 차단된 라이브가 뒤늦게 오지 않음


def test_scrub_rejected_outside_passthrough(proxy, warudo_socket):
    proxy.start_recording()
    assert proxy.begin_scrub() is False
    proxy.stop_recording("cleanup")


def test_scrub_frame_ignored_when_not_scrubbing(proxy, warudo_socket):
    proxy.scrub_frame(SCRUB_A)  # SCRUBBING 아님 -> 무시
    warudo_socket.settimeout(0.3)
    with pytest.raises(socket.timeout):
        warudo_socket.recvfrom(65535)


def test_end_scrub_fades_back_to_live(proxy, warudo_socket):
    # 라이브 살림 (fixture crossfade_live_ms=2000)
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    recv_text(warudo_socket)
    assert proxy.begin_scrub()
    proxy.scrub_frame("a-0|trackingStatus-1|=|head#0,0,0|")
    recv_text(warudo_socket)
    proxy.end_scrub()
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    value = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert value < 100  # 마지막 스크럽 프레임(a=0)과 블렌드되어 복귀 중


def test_end_scrub_without_live_no_fade(proxy, warudo_socket):
    assert proxy.begin_scrub()
    proxy.scrub_frame(SCRUB_A)
    recv_text(warudo_socket)
    proxy.end_scrub()
    assert proxy.mode is Mode.PASSTHROUGH
    assert proxy._fade_back_from is None  # 라이브 부재 -> 페이드 미준비
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: 새 테스트만 FAIL (`AttributeError: begin_scrub` 등)

- [ ] **Step 3: 구현** — `proxy.py` 수정:

`Mode`에 추가:

```python
    SCRUBBING = "scrubbing"
```

`__init__`에 추가:

```python
        self._last_scrub_packet: str | None = None
```

`_recv_loop`의 차단 조건 교체:

```python
            if mode is Mode.PLAYING or mode is Mode.SCRUBBING:
                continue  # 재생/스크럽 중엔 라이브 전달 차단 (수신 통계만 갱신)
```

스크럽 API 추가 (stop_playback 아래):

```python
    # -- 스크럽 (GUI 스레드에서 호출) --------------------------

    def begin_scrub(self) -> bool:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return False
            self._fade_back_from = None  # 이전 복귀 페이드 취소
            self._last_scrub_packet = None
            self._mode = Mode.SCRUBBING
            return True

    def scrub_frame(self, packet: str) -> None:
        if self.mode is not Mode.SCRUBBING:
            return
        frame = parse_packet(packet)
        if frame is not None and frame.blendshapes.get("trackingStatus") == 0:
            return  # Warudo가 무시하는 프레임: 송출 생략
        self._forward(packet)
        self._last_scrub_packet = packet

    def end_scrub(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.SCRUBBING:
                return
            self._mode = Mode.PASSTHROUGH
            if self.live_available() and self._last_scrub_packet:
                frame = parse_packet(self._last_scrub_packet)
                if frame is not None:
                    self._fade_back_from = frame
                    self._fade_back_until = (
                        time.perf_counter()
                        + self._config.crossfade_live_ms / 1000.0
                    )
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/ -v` → 전부 PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/proxy.py tests/test_proxy.py
rtk git commit -m 'feat: 스크럽 모드 (라이브 차단 + 1프레임 송출)'
```

---

### Task 6: Qt 앱 골격 — 다크 대시보드 + 설정 (tkinter 대체)

**Files:**
- Create: `requirements.txt`, `arkit_recorder/qt/__init__.py`(빈 파일), `arkit_recorder/qt/app.py`, `arkit_recorder/qt/settings_dialog.py`, `arkit_recorder/qt/main_window.py`
- Modify: `main.py`
- Delete: `arkit_recorder/gui.py`, `arkit_recorder/settings_dialog.py`

**Interfaces:**
- Consumes: `FaceProxy`(mode/receive_stats/start_recording/stop_recording/start_playback/stop_playback/apply_config/clips_dir/bind_error), `clips.list_clips/rename_clip/delete_clip`, `config.save_config`
- Produces:
  - `run_app(proxy, config, config_path) -> int`
  - `MainWindow(proxy, config, config_path)` — Task 7이 타임라인 위젯을 이 창에 배선
  - `open_settings(parent, proxy, config, config_path)` (qt/settings_dialog.py)

- [ ] **Step 1: PySide6 설치**

```bash
py -3.11 -m pip install 'PySide6>=6.6'
```

`requirements.txt` 생성:

```
PySide6>=6.6
```

- [ ] **Step 2: qt/app.py 작성**

```python
# arkit_recorder/qt/app.py
from __future__ import annotations

import sys

DARK_QSS = """
QWidget { background-color: #1e1f22; color: #e8e8e8; font-size: 13px; }
QMainWindow { background-color: #1e1f22; }
QPushButton {
    background-color: #33353a; border: 1px solid #45474d;
    border-radius: 4px; padding: 6px 10px;
}
QPushButton:hover { background-color: #3f4147; }
QPushButton:pressed { background-color: #2a2c30; }
QPushButton:disabled { color: #6a6a6a; background-color: #26272b; }
QListWidget {
    background-color: #26272b; border: 1px solid #3a3c42; border-radius: 4px;
}
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background-color: #3d5a80; color: #ffffff; }
QComboBox, QLineEdit {
    background-color: #26272b; border: 1px solid #3a3c42;
    border-radius: 4px; padding: 4px;
}
QCheckBox { spacing: 6px; }
QDialog { background-color: #1e1f22; }
"""


def run_app(proxy, config, config_path) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6가 설치되어 있지 않습니다. 설치: py -3.11 -m pip install PySide6")
        return 1
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    window = MainWindow(proxy, config, config_path)
    window.show()
    return app.exec()
```

- [ ] **Step 3: qt/settings_dialog.py 작성** (검증 로직은 기존 tkinter판과 동일)

```python
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
```

- [ ] **Step 4: qt/main_window.py 작성** (타임라인 자리는 QWidget 플레이스홀더 — Task 7이 교체)

```python
# arkit_recorder/qt/main_window.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..clips import delete_clip, list_clips, rename_clip
from ..config import Config
from ..proxy import FaceProxy, Mode
from .settings_dialog import open_settings

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
        self.setWindowTitle("ARKit Recorder")
        self.resize(900, 480)
        self._build_ui()
        self._refresh_clips()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(POLL_MS)

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

        # 우측: Task 7이 타임라인 위젯으로 교체하는 자리
        self._right_panel = QVBoxLayout()
        placeholder = QLabel("타임라인 (준비 중)")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._right_panel.addWidget(placeholder, 1)
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
        pass  # Task 7이 타임라인 로드로 교체

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
            self._proxy.stop_recording(name.strip())
            self._record_button.setText("녹화 시작")
            self._refresh_clips()

    def _start_ms_for_play(self) -> int:
        return 0  # Task 7이 플레이헤드 위치로 교체

    def _on_play(self) -> None:
        if self._proxy.mode is Mode.PLAYING:
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
        if self._proxy.mode is Mode.PLAYING:
            return
        info = self._selected_info()
        if info is None:
            return
        name, ok = QInputDialog.getText(
            self, "이름 변경", "새 이름:", text=info.name
        )
        if not ok or not name:
            return
        try:
            rename_clip(self._proxy.clips_dir, info.name, name)
        except ValueError as e:
            QMessageBox.warning(self, "이름 변경", str(e))
            return
        self._refresh_clips()

    def _on_delete(self) -> None:
        if self._proxy.mode is Mode.PLAYING:
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
```

- [ ] **Step 5: main.py 교체, tkinter 파일 삭제**

`main.py` 전체:

```python
# main.py
import sys
from pathlib import Path

from arkit_recorder.config import load_config
from arkit_recorder.proxy import FaceProxy
from arkit_recorder.qt.app import run_app

if getattr(sys, "frozen", False):
    # PyInstaller 빌드: __file__은 임시 해제 폴더를 가리키므로 exe 위치 기준
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    config_path = BASE_DIR / "config.json"
    config = load_config(config_path)
    proxy = FaceProxy(config, BASE_DIR)
    proxy.start()
    try:
        raise SystemExit(run_app(proxy, config, config_path))
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
```

```bash
rtk git rm arkit_recorder/gui.py arkit_recorder/settings_dialog.py
```

`arkit_recorder/qt/__init__.py`는 빈 파일로 생성.

- [ ] **Step 6: 검증**

```
python -m pytest tests/ -v                    → 전부 PASS (코어는 qt 미의존)
py -3.11 -c "import arkit_recorder.qt.app; import arkit_recorder.qt.main_window; import arkit_recorder.qt.settings_dialog; print('import ok')"
py -3.11 -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('main ok')"
```

GUI 실행 금지.

- [ ] **Step 7: 커밋**

```bash
rtk git add requirements.txt main.py arkit_recorder/qt
rtk git commit -m 'feat: PySide6 다크 대시보드로 GUI 교체'
```

---

### Task 7: 타임라인 위젯 + 메인 윈도우 통합

**Files:**
- Create: `arkit_recorder/qt/timeline_widget.py`
- Modify: `arkit_recorder/qt/main_window.py` (플레이스홀더 교체, 배선)

**Interfaces:**
- Consumes: Task 1 `timeline.py` 전 함수, Task 3 `playback_position_ms`/`start_playback(start_ms)`, Task 4 `recorder.live_wave` — proxy 경유 접근을 위해 `FaceProxy`에 공개 프로퍼티가 없으므로 `proxy._recorder.live_wave()`를 쓰지 않고 **`FaceProxy.live_wave()` 위임 메서드를 이 태스크에서 추가**한다(1줄, 테스트는 기존 recorder 테스트로 충분):

```python
    def live_wave(self) -> list[tuple[int, float]]:
        return self._recorder.live_wave()
```

- Task 5 `begin_scrub/scrub_frame/end_scrub`, Task 2 `validate_clip_name`
- Produces: `TimelineWidget(proxy)` — `set_data(data|None)`, `set_curve(name|None)`, `set_live_wave(wave|None)`, `set_playhead(ms)`, `playhead_ms()`, `trim_range() -> tuple[int, int]`

- [ ] **Step 1: timeline_widget.py 작성**

```python
# arkit_recorder/qt/timeline_widget.py
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..timeline import (
    TimelineData, activity_curve, blendshape_curve, frame_index_at,
)

MARKER_BAND = 12   # 상단 트림 핸들 밴드(px, 스펙 §4.2) — 이 아래는 스크럽 영역
MARGIN_X = 8
GRID_COLOR = QColor("#33353a")
CURVE_COLOR = QColor("#4f9cf9")
WAVE_COLOR = QColor("#d16d6d")
PLAYHEAD_COLOR = QColor("#e8e8e8")
TRIM_COLOR = QColor("#f0c674")
TRIM_FILL = QColor(240, 198, 116, 28)
TEXT_COLOR = QColor("#9a9a9a")


class TimelineWidget(QWidget):
    def __init__(self, proxy, parent=None):
        super().__init__(parent)
        self._proxy = proxy
        self._data: TimelineData | None = None
        self._curve: list[tuple[int, float]] = []
        self._curve_max = 1.0
        self._playhead_ms = 0
        self._trim_start = 0
        self._trim_end = 0
        self._live_wave: list[tuple[int, float]] | None = None
        self._dragging: str | None = None  # scrub | trim_start | trim_end
        self._last_scrub_index = -1
        self.setMinimumHeight(180)

    # -- 외부 API -------------------------------------------

    def set_data(self, data: TimelineData | None) -> None:
        self._data = data
        self._playhead_ms = 0
        self._trim_start = 0
        self._trim_end = data.duration_ms if data else 0
        self.set_curve(None)

    def set_curve(self, name: str | None) -> None:
        if self._data is None or not self._data.frames:
            self._curve = []
        elif name is None:
            self._curve = activity_curve(self._data)
        else:
            self._curve = [
                (t, float(v)) for t, v in blendshape_curve(self._data, name)
            ]
        self._curve_max = max((v for _, v in self._curve), default=0.0) or 1.0
        self.update()

    def set_live_wave(self, wave: list[tuple[int, float]] | None) -> None:
        self._live_wave = wave
        self.update()

    def set_playhead(self, ms: int) -> None:
        self._playhead_ms = ms
        self.update()

    def playhead_ms(self) -> int:
        return self._playhead_ms

    def trim_range(self) -> tuple[int, int]:
        return self._trim_start, self._trim_end

    def is_live(self) -> bool:
        return self._live_wave is not None

    # -- 좌표 변환 ------------------------------------------

    def _span_ms(self) -> int:
        if self._live_wave:
            return max((t for t, _ in self._live_wave), default=1000) or 1000
        if self._data and self._data.duration_ms > 0:
            return self._data.duration_ms
        return 1000

    def _ms_to_x(self, ms: int) -> float:
        usable = max(1, self.width() - 2 * MARGIN_X)
        return MARGIN_X + usable * ms / self._span_ms()

    def _x_to_ms(self, x: float) -> int:
        usable = max(1, self.width() - 2 * MARGIN_X)
        ratio = (x - MARGIN_X) / usable
        return round(max(0.0, min(1.0, ratio)) * self._span_ms())

    # -- 그리기 ---------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#232428"))
        if self._live_wave is not None:
            self._paint_curve(painter, self._live_wave, WAVE_COLOR)
            painter.setPen(TEXT_COLOR)
            painter.drawText(MARGIN_X + 4, 18, "녹화 중")
            return
        if self._data is None or not self._data.frames:
            painter.setPen(TEXT_COLOR)
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "프레임 없음"
            )
            return
        self._paint_grid(painter)
        self._paint_trim(painter)
        self._paint_curve(painter, self._curve, CURVE_COLOR)
        self._paint_playhead(painter)

    def _paint_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(GRID_COLOR, 1))
        span = self._span_ms()
        step = 1000
        while span / step > 20:  # 눈금이 20개를 넘으면 간격 확대
            step *= 5
        ms = 0
        while ms <= span:
            x = self._ms_to_x(ms)
            painter.drawLine(int(x), MARKER_BAND, int(x), self.height())
            painter.setPen(TEXT_COLOR)
            painter.drawText(int(x) + 2, self.height() - 4, f"{ms // 1000}s")
            painter.setPen(QPen(GRID_COLOR, 1))
            ms += step

    def _paint_curve(self, painter, curve, color) -> None:
        if not curve:
            return
        top = MARKER_BAND + 4
        bottom = self.height() - 16
        peak = max((v for _, v in curve), default=0.0) or 1.0
        points = [
            QPointF(
                self._ms_to_x(t),
                bottom - (bottom - top) * (v / peak),
            )
            for t, v in curve
        ]
        painter.setPen(QPen(color, 2))
        painter.drawPolyline(QPolygonF(points))

    def _paint_trim(self, painter: QPainter) -> None:
        x1 = self._ms_to_x(self._trim_start)
        x2 = self._ms_to_x(self._trim_end)
        painter.fillRect(
            int(x1), MARKER_BAND, int(x2 - x1), self.height() - MARKER_BAND,
            TRIM_FILL,
        )
        painter.setPen(QPen(TRIM_COLOR, 2))
        for x in (x1, x2):
            painter.drawLine(int(x), 0, int(x), self.height())
            handle = QPolygonF([
                QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, MARKER_BAND - 2),
            ])
            painter.setBrush(TRIM_COLOR)
            painter.drawPolygon(handle)

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._ms_to_x(self._playhead_ms)
        painter.setPen(QPen(PLAYHEAD_COLOR, 1))
        painter.drawLine(int(x), MARKER_BAND, int(x), self.height())

    # -- 마우스 (스크럽 / 트림) ------------------------------

    def mousePressEvent(self, event) -> None:
        if self._live_wave is not None or self._data is None or not self._data.frames:
            return
        x = event.position().x()
        if event.position().y() <= MARKER_BAND:
            # 트림 핸들: 가까운 쪽 마커를 잡는다 (±8px)
            if abs(x - self._ms_to_x(self._trim_start)) <= 8:
                self._dragging = "trim_start"
                return
            if abs(x - self._ms_to_x(self._trim_end)) <= 8:
                self._dragging = "trim_end"
                return
            return
        if self._proxy.begin_scrub():
            self._dragging = "scrub"
            self._last_scrub_index = -1
            self._scrub_to(x)

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._dragging == "scrub":
            self._scrub_to(x)
        elif self._dragging == "trim_start":
            self._trim_start = min(self._x_to_ms(x), self._trim_end)
            self.update()
        elif self._dragging == "trim_end":
            self._trim_end = max(self._x_to_ms(x), self._trim_start)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging == "scrub":
            self._proxy.end_scrub()
        self._dragging = None

    def _scrub_to(self, x: float) -> None:
        ms = self._x_to_ms(x)
        index = frame_index_at(self._data, ms)
        if index < 0:
            return
        if index != self._last_scrub_index:  # 프레임이 바뀐 경우에만 송출
            self._last_scrub_index = index
            t_ms, packet = self._data.frames[index]
            self._proxy.scrub_frame(packet)
            self._playhead_ms = t_ms
            self.update()
```

- [ ] **Step 2: main_window.py 배선** (수정 부분)

import 추가:

```python
from PySide6.QtWidgets import QComboBox  # 기존 import 목록에 추가

from ..clips import validate_clip_name   # 기존 clips import에 추가
from ..timeline import load_timeline, save_frames, trim
from .timeline_widget import TimelineWidget
```

`__init__`에 `self._timeline_data = None` 추가.

`_build_ui`의 우측 패널 플레이스홀더 블록을 다음으로 교체:

```python
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
```

`_on_clip_selected`를 다음으로 교체:

```python
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
```

핸들러 추가/교체:

```python
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
        if not ok or not name:
            return
        try:
            path = validate_clip_name(self._proxy.clips_dir, name)
        except ValueError as e:
            QMessageBox.warning(self, "구간 저장", str(e))
            return
        save_frames(frames, path)
        self._refresh_clips()
```

`__init__`의 poll 타이머 아래에 파형 전용 100ms 타이머 추가 (스펙 §3):

```python
        self._wave_timer = QTimer(self)
        self._wave_timer.timeout.connect(self._poll_wave)
        self._wave_timer.start(100)
```

`_poll` 끝에 추가 (버튼 상태 갱신 다음) 및 `_poll_wave` 메서드 추가:

```python
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
```

`FaceProxy.live_wave()` 위임 메서드를 `arkit_recorder/proxy.py`에 추가
(receive_stats 아래):

```python
    def live_wave(self) -> list[tuple[int, float]]:
        return self._recorder.live_wave()
```

- [ ] **Step 3: 검증**

```
python -m pytest tests/ -v      → 전부 PASS
py -3.11 -c "import arkit_recorder.qt.timeline_widget; import arkit_recorder.qt.main_window; print('import ok')"
```

GUI 실행 금지.

- [ ] **Step 4: 커밋**

```bash
rtk git add arkit_recorder/qt arkit_recorder/proxy.py
rtk git commit -m 'feat: 타임라인 위젯 (곡선/스크럽/트림/녹화 파형)'
```

---

## 수동 스모크 (구현 완료 후, 사용자 진행)

1. `py -3.11 main.py` — 다크 대시보드, 클립 목록/타임라인 표시
2. 클립 선택 → 활동량 곡선 표시, 콤보박스에서 jawOpen 등 선택 시 곡선 변경
3. 타임라인 드래그 → Warudo 아바타가 실시간으로 표정 변경, 놓으면 라이브 복귀
4. 트림 마커(상단 삼각형) 드래그 → 구간 저장 → 새 클립 생성 확인
5. 플레이헤드 위치에서 [재생] → 그 지점부터 재생, 재생 중 플레이헤드 이동
6. 녹화 시작 → 타임라인이 실시간 파형으로 전환, 정지 후 복귀
7. 설정 변경 (기존 기능 회귀 확인)
8. 확인 후 PyInstaller 재빌드 (PySide6 포함)
