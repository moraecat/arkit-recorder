# arkit-recorder 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 아이폰 iFacialMocap 트래킹(UDP 49983)을 패스스루·녹화하고, 아이폰 없이 Warudo로 재생 송출하는 상시 실행 프록시 프로그램.

**Architecture:** UDP 수신 스레드가 패킷을 Warudo로 전달하며(패스스루), 녹화 시 JSONL로 무손실 기록, 재생 시 라이브 전달을 차단하고 클립을 원래 타이밍으로 송출한다. 모드 경계에서는 패킷을 파싱-보간-재직렬화하는 크로스페이드로 표정 점프를 막는다. tkinter GUI가 프록시를 폴링·조작한다.

**Tech Stack:** Python 3.11, 표준 라이브러리만 (socket, threading, json, tkinter). 테스트: pytest 9.

**스펙:** `docs/superpowers/specs/2026-08-04-arkit-recorder-design.md` (모든 수치·규칙의 원본)

## Global Constraints

- 외부 의존성 금지 — 표준 라이브러리만 사용 (pytest는 테스트 전용)
- 코드·콘솔 출력·로그에 이모지 금지 (cp949 크래시 방지), ASCII와 한글만
- 기본 포트: 수신 49983, 전달 127.0.0.1:49984 / 크로스페이드 기본값: 라이브 경계 300ms, 루프 경계 500ms
- 녹화 파일: `clips/<이름>.jsonl`, 한 줄 = `{"t": <상대 ms 정수>, "d": "<원본 패킷 문자열>"}`
- `trackingStatus-0` 프레임: 기록은 하되 재생 송출은 생략
- 파싱 불가 패킷: 패스스루/녹화는 원본 그대로, 블렌딩만 생략
- 라이브 프레임 부재(최근 0.5초 수신 없음) 시 라이브 경계 크로스페이드 생략
- 테스트 실행: `python -m pytest tests/ -v` (셸 명령은 bash 기준, rtk 접두사 사용)
- 커밋 메시지에 큰따옴표 사용 금지 (PowerShell 호환 문제), bash에서 작은따옴표 사용

## 파일 구조 (전체)

```
E:\Works\arkit-recorder\
  main.py                엔트리포인트 (Task 10)
  arkit_recorder\
    __init__.py          빈 파일 (Task 1)
    protocol.py          Frame, parse_packet, serialize_frame (Task 1) + lerp_angle, blend_frames (Task 2)
    config.py            Config, load_config (Task 3)
    recorder.py          ClipRecorder (Task 4)
    player.py            ClipPlayer (Task 5, 6)
    proxy.py             Mode, FaceProxy (Task 7, 8)
    gui.py               run_gui (Task 10)
  tests\
    test_protocol.py     (Task 1, 2)
    test_config.py       (Task 3)
    test_recorder.py     (Task 4)
    test_player.py       (Task 5, 6)
    test_proxy.py        (Task 7, 8)
    test_proxy_e2e.py    (Task 9)
```

## 참조: iFacialMocap 패킷 포맷 (테스트 픽스처의 근거)

Warudo 디컴파일 파서(`iFacialMocapClient.cs`)와 동일한 규칙을 따른다:

- 공백 제거 후 유일한 `=`로 블렌드쉐이프부와 head부를 나눈다. `=`가 0개 또는 2개 이상이면 프레임 무효
- 블렌드쉐이프부: `이름-정수|` 반복. 첫 `-` 기준 분리 (음수값 `이름--3` 허용). 정수는 0~100 스케일
- head부: `head#pitch,yaw,roll[,x,y,z]|`, `leftEye#p,y,r|`, `rightEye#p,y,r|` (Euler 각도)
- 실제 패킷 예:
  `mouthSmile_R-32|eyeBlink_L-5|trackingStatus-1|=|head#28.98,-2.57,-6.64,-0.03,-0.10,-0.65|rightEye#6.02,2.44,0.25|leftEye#6.03,-1.66,-0.17|`

---

### Task 1: 프로젝트 골격 + protocol 파싱/직렬화

**Files:**
- Create: `arkit_recorder/__init__.py` (빈 파일)
- Create: `arkit_recorder/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `Frame` dataclass: `blendshapes: dict[str, int]` (삽입 순서 = 원본 순서), `head_rotation: tuple[float, float, float] | None`, `head_position: tuple[float, float, float] | None`, `left_eye: tuple[float, float, float] | None`, `right_eye: tuple[float, float, float] | None`
  - `parse_packet(text: str) -> Frame | None` — 무효 패킷(`=` 0개/2개 이상)이면 None
  - `serialize_frame(frame: Frame) -> str` — Warudo 파서가 읽을 수 있는 형식

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_protocol.py
import pytest

from arkit_recorder.protocol import Frame, parse_packet, serialize_frame

SAMPLE = (
    "mouthSmile_R-32|eyeBlink_L-5|trackingStatus-1|="
    "|head#28.98,-2.57,-6.64,-0.03,-0.1,-0.65"
    "|rightEye#6.02,2.44,0.25|leftEye#6.03,-1.66,-0.17|"
)


def test_parse_blendshapes():
    frame = parse_packet(SAMPLE)
    assert frame is not None
    assert frame.blendshapes == {
        "mouthSmile_R": 32, "eyeBlink_L": 5, "trackingStatus": 1,
    }
    assert list(frame.blendshapes) == ["mouthSmile_R", "eyeBlink_L", "trackingStatus"]


def test_parse_head_and_eyes():
    frame = parse_packet(SAMPLE)
    assert frame.head_rotation == (28.98, -2.57, -6.64)
    assert frame.head_position == (-0.03, -0.1, -0.65)
    assert frame.right_eye == (6.02, 2.44, 0.25)
    assert frame.left_eye == (6.03, -1.66, -0.17)


def test_parse_head_rotation_only():
    frame = parse_packet("a-1|=|head#1.0,2.0,3.0|")
    assert frame.head_rotation == (1.0, 2.0, 3.0)
    assert frame.head_position is None


def test_parse_negative_value():
    frame = parse_packet("browDown_L--3|=|head#0,0,0|")
    assert frame.blendshapes["browDown_L"] == -3


def test_parse_strips_spaces():
    frame = parse_packet("a-1 |= |head#1.0, 2.0,3.0|")
    assert frame.blendshapes["a"] == 1
    assert frame.head_rotation == (1.0, 2.0, 3.0)


def test_parse_invalid_equals_count():
    assert parse_packet("a-1|head#0,0,0|") is None      # '=' 없음
    assert parse_packet("a-1|=|b=2|head#0,0,0|") is None  # '=' 2개


def test_parse_skips_bad_tokens():
    frame = parse_packet("a-1|garbage|b-notanint|c-2|=|bad#x,y,z|head#0,0,0|")
    assert frame.blendshapes == {"a": 1, "c": 2}
    assert frame.head_rotation == (0.0, 0.0, 0.0)


def test_serialize_roundtrip():
    frame = parse_packet(SAMPLE)
    again = parse_packet(serialize_frame(frame))
    assert again == frame


def test_serialize_without_head_position():
    frame = Frame(blendshapes={"a": 1}, head_rotation=(1.5, 2.5, 3.5))
    again = parse_packet(serialize_frame(frame))
    assert again.head_rotation == (1.5, 2.5, 3.5)
    assert again.head_position is None
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_protocol.py -v`
예상: 전부 FAIL (`ModuleNotFoundError: arkit_recorder`)

- [ ] **Step 3: 구현**

`arkit_recorder/__init__.py`는 빈 파일로 생성. `arkit_recorder/protocol.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Frame:
    blendshapes: dict[str, int] = field(default_factory=dict)
    head_rotation: tuple[float, float, float] | None = None
    head_position: tuple[float, float, float] | None = None
    left_eye: tuple[float, float, float] | None = None
    right_eye: tuple[float, float, float] | None = None


def parse_packet(text: str) -> Frame | None:
    # Warudo iFacialMocapClient와 동일 규칙: 공백 제거, 유일한 '='로 분리
    compact = text.replace(" ", "")
    if compact.count("=") != 1:
        return None
    bs_part, head_part = compact.split("=", 1)
    frame = Frame()
    for token in bs_part.split("|"):
        name, sep, value = token.partition("-")
        if not sep or not name:
            continue
        try:
            frame.blendshapes[name] = int(value)
        except ValueError:
            continue
    for token in head_part.split("|"):
        name, sep, nums = token.partition("#")
        if not sep:
            continue
        try:
            values = tuple(float(v) for v in nums.split(","))
        except ValueError:
            continue
        if name == "head":
            if len(values) >= 6:
                frame.head_rotation = values[0:3]
                frame.head_position = values[3:6]
            elif len(values) >= 3:
                frame.head_rotation = values[0:3]
        elif name == "leftEye" and len(values) >= 3:
            frame.left_eye = values[0:3]
        elif name == "rightEye" and len(values) >= 3:
            frame.right_eye = values[0:3]
    return frame


def serialize_frame(frame: Frame) -> str:
    parts = [f"{name}-{value}" for name, value in frame.blendshapes.items()]
    tokens = []
    if frame.head_rotation is not None:
        nums = list(frame.head_rotation)
        if frame.head_position is not None:
            nums.extend(frame.head_position)
        tokens.append("head#" + ",".join(str(v) for v in nums))
    if frame.right_eye is not None:
        tokens.append("rightEye#" + ",".join(str(v) for v in frame.right_eye))
    if frame.left_eye is not None:
        tokens.append("leftEye#" + ",".join(str(v) for v in frame.left_eye))
    return "|".join(parts) + "|=|" + "|".join(tokens) + "|"
```

주의: `str(v)`는 Python float의 최단 왕복 표현이라 직렬화-재파싱 시 정밀도가 보존된다.
음수값 파싱: `partition("-")`은 첫 `-` 기준이므로 `browDown_L--3` → 이름 `browDown_L`, 값 `-3`.

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_protocol.py -v`
예상: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder tests
rtk git commit -m 'feat: iFacialMocap 패킷 파싱/직렬화 (protocol.py)'
```

---

### Task 2: protocol 프레임 보간 (blend_frames)

**Files:**
- Modify: `arkit_recorder/protocol.py` (함수 추가)
- Test: `tests/test_protocol.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `Frame`
- Produces:
  - `lerp_angle(a: float, b: float, t: float) -> float` — 최단 경로 각도 보간
  - `blend_frames(a: Frame, b: Frame, t: float) -> Frame` — t=0이면 a, t=1이면 b. 블렌드쉐이프는 반올림 정수, 회전은 각도 보간, 위치는 선형 보간. 한쪽에만 있는 키/필드는 있는 쪽 값 유지. 키 순서는 b 우선, a 전용 키는 뒤에

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_protocol.py`에 추가)

```python
from arkit_recorder.protocol import blend_frames, lerp_angle


def test_lerp_angle_shortest_path():
    assert lerp_angle(350.0, 10.0, 0.5) == pytest.approx(360.0)
    assert lerp_angle(10.0, 350.0, 0.5) == pytest.approx(0.0)
    assert lerp_angle(0.0, 90.0, 0.5) == pytest.approx(45.0)


def test_blend_blendshapes_rounded():
    a = Frame(blendshapes={"smile": 0, "trackingStatus": 1})
    b = Frame(blendshapes={"smile": 100, "trackingStatus": 1})
    mid = blend_frames(a, b, 0.5)
    assert mid.blendshapes["smile"] == 50
    assert mid.blendshapes["trackingStatus"] == 1


def test_blend_one_sided_keys_kept():
    a = Frame(blendshapes={"onlyA": 10})
    b = Frame(blendshapes={"onlyB": 20})
    mid = blend_frames(a, b, 0.5)
    assert mid.blendshapes == {"onlyB": 20, "onlyA": 10}


def test_blend_head_rotation_shortest_path():
    a = Frame(head_rotation=(350.0, 0.0, 0.0), head_position=(0.0, 0.0, 0.0))
    b = Frame(head_rotation=(10.0, 0.0, 0.0), head_position=(1.0, 0.0, 0.0))
    mid = blend_frames(a, b, 0.5)
    assert mid.head_rotation[0] == pytest.approx(360.0)
    assert mid.head_position[0] == pytest.approx(0.5)


def test_blend_one_sided_head_kept():
    a = Frame(head_rotation=(1.0, 2.0, 3.0))
    b = Frame()
    assert blend_frames(a, b, 0.5).head_rotation == (1.0, 2.0, 3.0)
    assert blend_frames(b, a, 0.5).head_rotation == (1.0, 2.0, 3.0)


def test_blend_endpoints():
    a = Frame(blendshapes={"x": 0}, left_eye=(0.0, 0.0, 0.0))
    b = Frame(blendshapes={"x": 80}, left_eye=(10.0, 0.0, 0.0))
    assert blend_frames(a, b, 0.0).blendshapes["x"] == 0
    assert blend_frames(a, b, 1.0).blendshapes["x"] == 80
    assert blend_frames(a, b, 1.0).left_eye[0] == pytest.approx(10.0)
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_protocol.py -v`
예상: 새 테스트만 FAIL (`ImportError: blend_frames`)

- [ ] **Step 3: 구현** (`arkit_recorder/protocol.py`에 추가)

```python
def lerp_angle(a: float, b: float, t: float) -> float:
    delta = ((b - a + 180.0) % 360.0) - 180.0
    return a + delta * t


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_tuple(a, b, t, angular):
    if a is None:
        return b
    if b is None:
        return a
    fn = lerp_angle if angular else _lerp
    return tuple(fn(x, y, t) for x, y in zip(a, b))


def blend_frames(a: Frame, b: Frame, t: float) -> Frame:
    out = Frame()
    for name, vb in b.blendshapes.items():
        va = a.blendshapes.get(name)
        out.blendshapes[name] = vb if va is None else round(_lerp(va, vb, t))
    for name, va in a.blendshapes.items():
        if name not in out.blendshapes:
            out.blendshapes[name] = va
    out.head_rotation = _blend_tuple(a.head_rotation, b.head_rotation, t, angular=True)
    out.head_position = _blend_tuple(a.head_position, b.head_position, t, angular=False)
    out.left_eye = _blend_tuple(a.left_eye, b.left_eye, t, angular=True)
    out.right_eye = _blend_tuple(a.right_eye, b.right_eye, t, angular=True)
    return out
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_protocol.py -v`
예상: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/protocol.py tests/test_protocol.py
rtk git commit -m 'feat: 프레임 보간 blend_frames, lerp_angle 추가'
```

---

### Task 3: config 로드/자동 생성

**Files:**
- Create: `arkit_recorder/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `Config` dataclass: `listen_port: int = 49983`, `forward_host: str = "127.0.0.1"`, `forward_port: int = 49984`, `clips_dir: str = "clips"`, `crossfade_live_ms: int = 300`, `crossfade_loop_ms: int = 500`
  - `load_config(path: Path) -> Config` — 파일이 없으면 기본값으로 생성 후 반환, 알 수 없는 키는 무시

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_config.py
import json

from arkit_recorder.config import Config, load_config


def test_creates_default_file(tmp_path):
    path = tmp_path / "config.json"
    config = load_config(path)
    assert config == Config()
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["listen_port"] == 49983
    assert saved["forward_port"] == 49984
    assert saved["crossfade_live_ms"] == 300
    assert saved["crossfade_loop_ms"] == 500


def test_loads_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"listen_port": 15000, "unknown_key": 1}), encoding="utf-8")
    config = load_config(path)
    assert config.listen_port == 15000
    assert config.forward_port == 49984  # 명시 안 된 항목은 기본값
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_config.py -v`
예상: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/config.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Config:
    listen_port: int = 49983
    forward_host: str = "127.0.0.1"
    forward_port: int = 49984
    clips_dir: str = "clips"
    crossfade_live_ms: int = 300
    crossfade_loop_ms: int = 500


def load_config(path: Path) -> Config:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Config)}
        return Config(**{k: v for k, v in data.items() if k in known})
    config = Config()
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return config
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_config.py -v`
예상: PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/config.py tests/test_config.py
rtk git commit -m 'feat: config.json 로드/자동 생성'
```

---

### Task 4: recorder — JSONL 스트리밍 녹화

**Files:**
- Create: `arkit_recorder/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `ClipRecorder(tmp_path: Path, now=time.perf_counter)`
  - `.start() -> None` — 임시 파일 열고 기록 시작 (긴 녹화도 메모리 안 쌓이게 즉시 파일 기록)
  - `.feed(packet: str) -> None` — 기록 중이 아니면 무시. 스레드 안전 (수신 스레드에서 호출됨)
  - `.stop_and_save(final_path: Path) -> int` — 임시 파일을 최종 경로로 rename, 프레임 수 반환
  - `.discard() -> None` — 녹화 취소, 임시 파일 삭제
  - `.is_recording: bool` (property)
  - `.frame_count: int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_recorder.py
import json

from arkit_recorder.recorder import ClipRecorder


class FakeClock:
    def __init__(self):
        self.time = 100.0

    def now(self):
        return self.time


def test_records_relative_ms(tmp_path):
    clock = FakeClock()
    rec = ClipRecorder(tmp_path / "_tmp.jsonl", now=clock.now)
    rec.start()
    rec.feed("a-1|=|head#0,0,0|")
    clock.time += 0.1
    rec.feed("a-2|=|head#0,0,0|")
    final = tmp_path / "clip.jsonl"
    count = rec.stop_and_save(final)
    assert count == 2
    assert not (tmp_path / "_tmp.jsonl").exists()
    lines = [json.loads(x) for x in final.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"t": 0, "d": "a-1|=|head#0,0,0|"}
    assert lines[1] == {"t": 100, "d": "a-2|=|head#0,0,0|"}


def test_feed_ignored_when_not_recording(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.feed("a-1|=|head#0,0,0|")  # start 전 — 예외 없이 무시
    assert rec.frame_count == 0
    assert not rec.is_recording


def test_discard_removes_tmp(tmp_path):
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.start()
    rec.feed("a-1|=|head#0,0,0|")
    rec.discard()
    assert not (tmp_path / "_tmp.jsonl").exists()
    assert not rec.is_recording
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_recorder.py -v`
예상: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/recorder.py
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class ClipRecorder:
    def __init__(self, tmp_path: Path, now=time.perf_counter):
        self._tmp_path = tmp_path
        self._now = now
        self._lock = threading.Lock()
        self._file = None
        self._start_time = 0.0
        self.frame_count = 0

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    def start(self) -> None:
        with self._lock:
            self._tmp_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self._tmp_path, "w", encoding="utf-8")
            self._start_time = self._now()
            self.frame_count = 0

    def feed(self, packet: str) -> None:
        with self._lock:
            if self._file is None:
                return
            t_ms = int((self._now() - self._start_time) * 1000)
            self._file.write(json.dumps({"t": t_ms, "d": packet}) + "\n")
            self.frame_count += 1

    def stop_and_save(self, final_path: Path) -> int:
        with self._lock:
            if self._file is None:
                return 0
            self._file.close()
            self._file = None
            final_path.parent.mkdir(parents=True, exist_ok=True)
            self._tmp_path.replace(final_path)
            return self.frame_count

    def discard(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._tmp_path.unlink(missing_ok=True)
```

주의: `feed()`는 UDP 수신 스레드에서, `stop_and_save()`는 GUI 스레드에서 불리므로
락으로 파일 닫힘/쓰기 경쟁을 막는다.

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_recorder.py -v`
예상: PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/recorder.py tests/test_recorder.py
rtk git commit -m 'feat: JSONL 스트리밍 녹화 ClipRecorder'
```

---

### Task 5: player — 타이밍 재생, trackingStatus 생략, 손상 라인 스킵

**Files:**
- Create: `arkit_recorder/player.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: Task 1~2의 `parse_packet`, `serialize_frame`, `blend_frames`
- Produces:
  - `ClipPlayer(send: Callable[[str], None], now=time.perf_counter, sleep=time.sleep, crossfade_live_ms: int = 300, crossfade_loop_ms: int = 500)`
  - `.load(path: Path) -> int` — JSONL 로드, 프레임 수 반환. 손상 라인은 건너뛰고 `.skipped_lines`에 집계
  - `.play(loop: bool = False, lead_in_packet: str | None = None) -> None` — 블로킹. 호출자가 별도 스레드에서 실행. 타임스탬프 기반 스케줄링(누적 오차 보정), `trackingStatus-0` 프레임은 송출 생략
  - `.stop() -> None` — 다른 스레드에서 호출 가능
  - `.is_playing: bool`, `.last_sent_packet: str | None`, `.skipped_lines: int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_player.py
import json

from arkit_recorder.player import ClipPlayer
from arkit_recorder.protocol import parse_packet


class FakeClock:
    def __init__(self):
        self.time = 0.0

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.time += seconds


def write_clip(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )


def make_player(clock, send, **kwargs):
    return ClipPlayer(send=send, now=clock.now, sleep=clock.sleep, **kwargs)


def test_load_skips_corrupt_lines(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(
        '{"t": 0, "d": "a-1|=|head#0,0,0|"}\n'
        "not json at all\n"
        '{"t": 100}\n'
        '{"t": 200, "d": "a-2|=|head#0,0,0|"}\n',
        encoding="utf-8",
    )
    player = ClipPlayer(send=lambda p: None)
    assert player.load(path) == 2
    assert player.skipped_lines == 2


def test_playback_timing(tmp_path):
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
    player.play()
    assert [t for t, _ in sent] == [0.0, 0.1, 0.25]
    assert [parse_packet(p).blendshapes["a"] for _, p in sent] == [1, 2, 3]
    assert not player.is_playing
    assert player.last_sent_packet == "a-3|trackingStatus-1|=|head#0,0,0|"


def test_tracking_status_zero_skipped(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-2|trackingStatus-0|=|head#0,0,0|"},
        {"t": 200, "d": "a-3|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p))
    player.load(path)
    player.play()
    assert [parse_packet(p).blendshapes["a"] for p in sent] == [1, 3]


def test_unparseable_frame_sent_verbatim(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [{"t": 0, "d": "no equals sign here"}])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p))
    player.load(path)
    player.play()
    assert sent == ["no equals sign here"]


def test_stop_interrupts(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i * 100, "d": f"a-{i}|trackingStatus-1|=|head#0,0,0|"}
        for i in range(100)
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) >= 5:
            player.stop()

    player = make_player(clock, send)
    player.load(path)
    player.play()
    # 5번째 송출 직후 stop -> 다음 프레임 진입 전에 중단
    assert len(sent) == 5
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_player.py -v`
예상: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/player.py
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from .protocol import Frame, blend_frames, parse_packet, serialize_frame


class ClipPlayer:
    def __init__(
        self,
        send: Callable[[str], None],
        now=time.perf_counter,
        sleep=time.sleep,
        crossfade_live_ms: int = 300,
        crossfade_loop_ms: int = 500,
    ):
        self._send = send
        self._now = now
        self._sleep = sleep
        self._crossfade_live_ms = crossfade_live_ms
        self._crossfade_loop_ms = crossfade_loop_ms
        self._frames: list[tuple[int, str]] = []
        self._stop_event = threading.Event()
        self.is_playing = False
        self.last_sent_packet: str | None = None
        self.skipped_lines = 0

    def load(self, path: Path) -> int:
        frames = []
        self.skipped_lines = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    frames.append((int(entry["t"]), str(entry["d"])))
                except (ValueError, KeyError, TypeError):
                    self.skipped_lines += 1
        self._frames = frames
        return len(frames)

    def play(self, loop: bool = False, lead_in_packet: str | None = None) -> None:
        # 블로킹 — 호출자는 별도 스레드에서 실행한다
        if not self._frames:
            return
        self._stop_event.clear()
        self.is_playing = True
        try:
            fade_src = parse_packet(lead_in_packet) if lead_in_packet else None
            fade_ms = self._crossfade_live_ms
            while not self._stop_event.is_set():
                start = self._now()
                for t_ms, packet in self._frames:
                    if self._stop_event.is_set():
                        return
                    delay = start + t_ms / 1000.0 - self._now()
                    if delay > 0:
                        self._sleep(delay)
                    out = self._prepare(packet, t_ms, fade_src, fade_ms)
                    if out is not None:
                        self._send(out)
                        self.last_sent_packet = out
                if not loop:
                    return
                # 루프 경계: 마지막 송출 프레임에서 클립 처음으로 크로스페이드
                fade_src = (
                    parse_packet(self.last_sent_packet)
                    if self.last_sent_packet else None
                )
                fade_ms = self._crossfade_loop_ms
        finally:
            self.is_playing = False

    def _prepare(
        self, packet: str, t_ms: int, fade_src: Frame | None, fade_ms: int
    ) -> str | None:
        frame = parse_packet(packet)
        if frame is None:
            return packet  # 파싱 불가: 원본 그대로, 블렌딩만 생략
        if frame.blendshapes.get("trackingStatus") == 0:
            return None  # Warudo가 무시하는 프레임: 송출 생략
        if fade_src is not None and fade_ms > 0 and t_ms < fade_ms:
            t = t_ms / fade_ms
            return serialize_frame(blend_frames(fade_src, frame, t))
        return packet

    def stop(self) -> None:
        self._stop_event.set()
```

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_player.py -v`
예상: PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/player.py tests/test_player.py
rtk git commit -m 'feat: 클립 재생 스케줄러 ClipPlayer'
```

---

### Task 6: player — 리드인 크로스페이드와 루프

**Files:**
- Modify: `arkit_recorder/player.py` (Task 5 구현에 이미 포함된 로직의 검증 — 테스트만 추가. 테스트가 실패하면 구현 수정)
- Test: `tests/test_player.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 5의 `ClipPlayer`
- Produces: 동작 보증 — `play(lead_in_packet=...)` 시작 크로스페이드, `play(loop=True)` 루프 경계 크로스페이드

- [ ] **Step 1: 테스트 작성** (`tests/test_player.py`에 추가)

```python
def test_lead_in_crossfade(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "smile-100|trackingStatus-1|=|head#0,0,0|"},
        {"t": 150, "d": "smile-100|trackingStatus-1|=|head#0,0,0|"},
        {"t": 300, "d": "smile-100|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p), crossfade_live_ms=300)
    player.load(path)
    player.play(lead_in_packet="smile-0|trackingStatus-1|=|head#0,0,0|")
    values = [parse_packet(p).blendshapes["smile"] for p in sent]
    # t=0ms: 리드인 100%, t=150ms: 50% 블렌드, t=300ms: 크로스페이드 종료(원본)
    assert values == [0, 50, 100]
    # trackingStatus는 블렌드 후에도 1 유지
    assert all(parse_packet(p).blendshapes["trackingStatus"] == 1 for p in sent)


def test_no_lead_in_no_crossfade(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [{"t": 0, "d": "smile-100|trackingStatus-1|=|head#0,0,0|"}])
    clock = FakeClock()
    sent = []
    player = make_player(clock, lambda p: sent.append(p), crossfade_live_ms=300)
    player.load(path)
    player.play(lead_in_packet=None)  # 라이브 부재: 즉시 원본 송출
    assert sent == ["smile-100|trackingStatus-1|=|head#0,0,0|"]


def test_loop_boundary_crossfade(tmp_path):
    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": 0, "d": "smile-0|trackingStatus-1|=|head#0,0,0|"},
        {"t": 200, "d": "smile-0|trackingStatus-1|=|head#0,0,0|"},
        {"t": 400, "d": "smile-100|trackingStatus-1|=|head#0,0,0|"},
    ])
    clock = FakeClock()
    sent = []

    def send(p):
        sent.append(p)
        if len(sent) >= 6:  # 두 바퀴째 끝에서 정지
            player.stop()

    player = make_player(clock, send, crossfade_loop_ms=500)
    player.load(path)
    player.play(loop=True)
    values = [parse_packet(p).blendshapes["smile"] for p in sent]
    # 1바퀴 (리드인 없음, 원본 그대로): [0, 0, 100]
    # 2바퀴 (fade_src = 직전 송출 100, fade 500ms):
    #   t=0ms:   blend(100, 0, 0.0)   = 100  <- 경계 점프 없음
    #   t=200ms: blend(100, 0, 0.4)   = 60   <- 클립 값으로 수렴 중
    #   t=400ms: blend(100, 100, 0.8) = 100
    assert values == [0, 0, 100, 100, 60, 100]
```

- [ ] **Step 2: 테스트 실행**

실행: `python -m pytest tests/test_player.py -v`
예상: Task 5 구현이 이미 이 동작을 포함하므로 PASS가 정상. FAIL이면 Task 5의
`play()`/`_prepare()` 크로스페이드 분기를 테스트가 요구하는 수치에 맞게 수정한다.

- [ ] **Step 3: 커밋**

```bash
rtk git add tests/test_player.py arkit_recorder/player.py
rtk git commit -m 'test: 크로스페이드 리드인/루프 경계 검증'
```

---

### Task 7: proxy — UDP 패스스루, 녹화, 수신 통계

**Files:**
- Create: `arkit_recorder/proxy.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Consumes: `Config`(Task 3), `ClipRecorder`(Task 4), `ClipPlayer`(Task 5), `parse_packet`/`serialize_frame`/`blend_frames`(Task 1~2)
- Produces:
  - `Mode` enum: `PASSTHROUGH`, `RECORDING`, `PLAYING`
  - `FaceProxy(config: Config, base_dir: Path)`
  - `.start() -> None` — 수신 소켓 바인드(실패 시 `.bind_error: str | None`에 사유) + 수신 스레드 시작. `.bound_port: int | None`에 실제 바인드 포트(테스트가 listen_port=0으로 임의 포트 사용)
  - `.stop() -> None`
  - `.mode: Mode` (property), `.receive_stats() -> tuple[int, float | None]` — (최근 1초 수신 패킷 수, 마지막 수신 후 경과 초. 수신 이력 없으면 None)
  - `.start_recording() -> None`, `.stop_recording(name: str) -> Path`
  - `.start_playback(clip_path: Path, loop: bool) -> int` (Task 8), `.stop_playback() -> None` (Task 8)
  - `.clips_dir: Path` — GUI가 클립 목록 스캔에 사용

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_proxy.py
import socket
import time
from pathlib import Path

import pytest

from arkit_recorder.config import Config
from arkit_recorder.proxy import FaceProxy, Mode

PACKET = "a-1|trackingStatus-1|=|head#0,0,0|"


@pytest.fixture
def warudo_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    yield sock
    sock.close()


@pytest.fixture
def proxy(tmp_path, warudo_socket):
    config = Config(
        listen_port=0,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    p = FaceProxy(config, tmp_path)
    p.start()
    assert p.bind_error is None
    yield p
    p.stop()


def send_to_proxy(proxy, text=PACKET):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(text.encode("ascii"), ("127.0.0.1", proxy.bound_port))
    sock.close()


def recv_text(warudo_socket):
    data, _ = warudo_socket.recvfrom(65535)
    return data.decode("ascii")


def test_passthrough_forwards_verbatim(proxy, warudo_socket):
    send_to_proxy(proxy)
    assert recv_text(warudo_socket) == PACKET
    assert proxy.mode is Mode.PASSTHROUGH


def test_receive_stats_updates(proxy, warudo_socket):
    hz, since = proxy.receive_stats()
    assert hz == 0 and since is None
    send_to_proxy(proxy)
    recv_text(warudo_socket)
    hz, since = proxy.receive_stats()
    assert hz >= 1
    assert since is not None and since < 1.0


def test_recording_saves_and_keeps_forwarding(proxy, warudo_socket, tmp_path):
    proxy.start_recording()
    assert proxy.mode is Mode.RECORDING
    for i in range(3):
        send_to_proxy(proxy, f"a-{i}|trackingStatus-1|=|head#0,0,0|")
        assert recv_text(warudo_socket) == f"a-{i}|trackingStatus-1|=|head#0,0,0|"
    time.sleep(0.1)  # 수신 스레드의 feed 완료 대기
    clip_path = proxy.stop_recording("mytest")
    assert proxy.mode is Mode.PASSTHROUGH
    assert clip_path == tmp_path / "clips" / "mytest.jsonl"
    lines = clip_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_bind_error_reported(tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    port = blocker.getsockname()[1]
    p = FaceProxy(Config(listen_port=port), tmp_path)
    p.start()
    assert p.bind_error is not None
    assert str(port) in p.bind_error
    blocker.close()
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# arkit_recorder/proxy.py
from __future__ import annotations

import socket
import threading
import time
from collections import deque
from enum import Enum
from pathlib import Path

from .config import Config
from .player import ClipPlayer
from .protocol import Frame, blend_frames, parse_packet, serialize_frame
from .recorder import ClipRecorder

LIVE_TIMEOUT = 0.5  # Warudo와 같은 기준: 이 시간 수신 없으면 트래킹 끊김


class Mode(Enum):
    PASSTHROUGH = "passthrough"
    RECORDING = "recording"
    PLAYING = "playing"


class FaceProxy:
    def __init__(self, config: Config, base_dir: Path):
        self._config = config
        self.clips_dir = base_dir / config.clips_dir
        self._mode = Mode.PASSTHROUGH
        self._mode_lock = threading.Lock()
        self._recv_socket = None
        self._send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._forward_addr = (config.forward_host, config.forward_port)
        self._stop_event = threading.Event()
        self._recv_thread = None
        self._player_thread = None
        self._recorder = ClipRecorder(self.clips_dir / "_recording.tmp.jsonl")
        self._player: ClipPlayer | None = None
        self._recv_times = deque(maxlen=120)
        self._last_recv_time: float | None = None
        self._last_live_packet: str | None = None
        self._fade_back_from: Frame | None = None
        self._fade_back_until = 0.0
        self.bind_error: str | None = None
        self.bound_port: int | None = None

    @property
    def mode(self) -> Mode:
        return self._mode

    def start(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.bind(("0.0.0.0", self._config.listen_port))
        except OSError as e:
            self.bind_error = (
                f"포트 {self._config.listen_port} 바인드 실패 "
                f"(다른 프로그램이 사용 중일 수 있음): {e}"
            )
            return
        self._recv_socket = sock
        self.bound_port = sock.getsockname()[1]
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.stop_playback()
        if self._recv_socket is not None:
            self._recv_socket.close()
        if self._recorder.is_recording:
            self._recorder.discard()
        self._send_socket.close()

    def receive_stats(self) -> tuple[int, float | None]:
        now = time.perf_counter()
        hz = sum(1 for t in self._recv_times if now - t <= 1.0)
        since = None if self._last_recv_time is None else now - self._last_recv_time
        return hz, since

    def live_available(self) -> bool:
        return (
            self._last_recv_time is not None
            and time.perf_counter() - self._last_recv_time <= LIVE_TIMEOUT
        )

    # ── 수신 스레드 ──────────────────────────────

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, _ = self._recv_socket.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            packet = data.decode("ascii", errors="replace")
            now = time.perf_counter()
            self._recv_times.append(now)
            self._last_recv_time = now
            self._last_live_packet = packet
            mode = self._mode
            if mode is Mode.PLAYING:
                continue  # 재생 중엔 라이브 전달 차단 (수신 통계만 갱신)
            out = self._apply_fade_back(packet, now)
            self._forward(out)
            if mode is Mode.RECORDING:
                self._recorder.feed(packet)  # 페이드 보정 전 원본을 기록

    def _forward(self, packet: str) -> None:
        try:
            self._send_socket.sendto(
                packet.encode("ascii", errors="replace"), self._forward_addr
            )
        except OSError:
            pass

    def _apply_fade_back(self, packet: str, now: float) -> str:
        # 재생 종료 직후 crossfade_live_ms 동안 라이브로 부드럽게 복귀
        if self._fade_back_from is None or now >= self._fade_back_until:
            return packet
        live = parse_packet(packet)
        if live is None:
            return packet
        total = self._config.crossfade_live_ms / 1000.0
        t = 1.0 - (self._fade_back_until - now) / total
        return serialize_frame(blend_frames(self._fade_back_from, live, t))

    # ── 녹화 조작 (GUI 스레드에서 호출) ──────────

    def start_recording(self) -> None:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return
            self._recorder.start()
            self._mode = Mode.RECORDING

    def stop_recording(self, name: str) -> Path:
        with self._mode_lock:
            path = self.clips_dir / (name + ".jsonl")
            self._recorder.stop_and_save(path)
            if self._mode is Mode.RECORDING:
                self._mode = Mode.PASSTHROUGH
            return path

    # ── 재생 조작 (Task 8에서 구현) ──────────────

    def start_playback(self, clip_path: Path, loop: bool) -> int:
        raise NotImplementedError

    def stop_playback(self) -> None:
        player = self._player
        if player is not None:
            player.stop()
```

주의: `_recv_loop`의 모드 확인과 `stop_recording`의 파일 닫기 사이에 경쟁이
있지만, `ClipRecorder.feed`가 내부 락과 `_file is None` 확인으로 안전하게
무시한다 (Task 4).

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: PASS (start_playback 테스트는 아직 없음)

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/proxy.py tests/test_proxy.py
rtk git commit -m 'feat: UDP 패스스루/녹화 프록시 FaceProxy'
```

---

### Task 8: proxy — 재생 통합과 라이브 복귀 크로스페이드

**Files:**
- Modify: `arkit_recorder/proxy.py` (`start_playback` 구현, 헬퍼 추가)
- Test: `tests/test_proxy.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 7의 `FaceProxy`, Task 5의 `ClipPlayer`
- Produces:
  - `.start_playback(clip_path: Path, loop: bool) -> int` — 로드된 프레임 수 반환 (0이면 시작 안 함). 라이브가 살아 있으면(0.5초 내 수신) 마지막 라이브 패킷을 리드인으로 전달. 재생 스레드 종료 시 자동으로 PASSTHROUGH 복귀 + 복귀 크로스페이드 준비
  - `.stop_playback() -> None`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_proxy.py`에 추가)

```python
import json as jsonlib

from arkit_recorder.protocol import parse_packet


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def make_clip(proxy, entries):
    proxy.clips_dir.mkdir(parents=True, exist_ok=True)
    path = proxy.clips_dir / "test.jsonl"
    path.write_text(
        "\n".join(jsonlib.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return path


def test_playback_blocks_live_and_sends_clip(proxy, warudo_socket):
    # 이 테스트에서는 사전 라이브 수신이 없으므로 리드인 크로스페이드도 없다
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-10|trackingStatus-1|=|head#0,0,0|"},
        {"t": 50, "d": "a-20|trackingStatus-1|=|head#0,0,0|"},
    ])
    count = proxy.start_playback(clip, loop=False)
    assert count == 2
    assert proxy.mode is Mode.PLAYING
    send_to_proxy(proxy, "live-99|trackingStatus-1|=|head#0,0,0|")  # 차단돼야 함
    received = [recv_text(warudo_socket), recv_text(warudo_socket)]
    values = [parse_packet(p).blendshapes["a"] for p in received]
    assert values == [10, 20]
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_playback_loop_and_stop(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 30, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=True)
    for _ in range(5):  # 루프이므로 클립 길이 이상 수신됨
        recv_text(warudo_socket)
    proxy.stop_playback()
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_fade_back_to_live(proxy, warudo_socket):
    # 라이브를 먼저 살려둔다 (0.5초 내 수신 이력 -> 리드인/복귀 페이드 모두 발동)
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    recv_text(warudo_socket)
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-0|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-0|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=False)
    # 리드인 (fade 2000ms): t=0ms -> blend(100, 0, 0.0) = 100
    first = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert first == 100
    # t=100ms -> blend(100, 0, 0.05) = 95
    second = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert second == 95
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
    # 복귀 직후 라이브 패킷은 마지막 재생 프레임(a=95)과 블렌드되어 100 미만
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    value = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert 95 <= value < 100  # crossfade_live_ms=2000 창 안
```

- [ ] **Step 2: 실패 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: 새 테스트 FAIL (`NotImplementedError`)

- [ ] **Step 3: 구현** (`arkit_recorder/proxy.py`의 `start_playback` 교체 + 헬퍼 추가)

```python
    def start_playback(self, clip_path: Path, loop: bool) -> int:
        with self._mode_lock:
            if self._mode is not Mode.PASSTHROUGH:
                return 0
            player = ClipPlayer(
                send=self._forward,
                crossfade_live_ms=self._config.crossfade_live_ms,
                crossfade_loop_ms=self._config.crossfade_loop_ms,
            )
            count = player.load(clip_path)
            if count == 0:
                return 0
            lead_in = self._last_live_packet if self.live_available() else None
            self._player = player
            self._fade_back_from = None  # 이전 복귀 페이드 취소
            self._mode = Mode.PLAYING
        self._player_thread = threading.Thread(
            target=self._run_player, args=(player, loop, lead_in), daemon=True
        )
        self._player_thread.start()
        return count

    def _run_player(self, player: ClipPlayer, loop: bool, lead_in: str | None) -> None:
        try:
            player.play(loop=loop, lead_in_packet=lead_in)
        finally:
            self._finish_playback(player)

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

- [ ] **Step 4: 통과 확인**

실행: `python -m pytest tests/test_proxy.py -v`
예상: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/proxy.py tests/test_proxy.py
rtk git commit -m 'feat: 클립 재생 통합, 라이브 복귀 크로스페이드'
```

---

### Task 9: E2E 시나리오 테스트

**Files:**
- Test: `tests/test_proxy_e2e.py`

**Interfaces:**
- Consumes: 전체 스택 (`FaceProxy`, `Config`)
- Produces: 가짜 아이폰 → 프록시 → 가짜 Warudo 전체 흐름 검증

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_proxy_e2e.py
# 가짜 아이폰(UDP 송신) -> FaceProxy -> 가짜 Warudo(UDP 수신) 전체 시나리오
import json
import socket
import time

import pytest

from arkit_recorder.config import Config
from arkit_recorder.protocol import parse_packet
from arkit_recorder.proxy import FaceProxy, Mode


def make_packet(i):
    return f"jawOpen-{i}|eyeBlink_L-{i * 2}|trackingStatus-1|=|head#{i}.0,0,0|"


def test_full_scenario(tmp_path):
    warudo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    warudo.bind(("127.0.0.1", 0))
    warudo.settimeout(2.0)
    phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    config = Config(listen_port=0, forward_port=warudo.getsockname()[1])
    proxy = FaceProxy(config, tmp_path)
    proxy.start()
    assert proxy.bind_error is None
    addr = ("127.0.0.1", proxy.bound_port)

    try:
        # 1) 패스스루: 폰 패킷이 그대로 Warudo에 도착
        phone.sendto(make_packet(1).encode("ascii"), addr)
        data, _ = warudo.recvfrom(65535)
        assert data.decode("ascii") == make_packet(1)

        # 2) 녹화: 5 프레임 기록, 패스스루 유지
        proxy.start_recording()
        for i in range(5):
            phone.sendto(make_packet(i).encode("ascii"), addr)
            warudo.recvfrom(65535)  # 전달 확인
            time.sleep(0.02)
        time.sleep(0.1)
        clip_path = proxy.stop_recording("e2e")
        lines = clip_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        entries = [json.loads(x) for x in lines]
        # 첫 프레임은 start_recording 시점 기준 수 ms 뒤에 도착한다
        assert 0 <= entries[0]["t"] < 500
        assert all(entries[i]["t"] <= entries[i + 1]["t"] for i in range(4))

        # 3) 재생: 라이브 차단 + 클립 프레임 수신
        # 마지막 폰 패킷에서 0.5초 넘게 기다려 리드인 크로스페이드가
        # 걸리지 않게 한다 (원본 값 그대로 수신되어야 검증이 단순해짐)
        time.sleep(0.6)
        count = proxy.start_playback(clip_path, loop=False)
        assert count == 5
        received = []
        for _ in range(5):
            data, _ = warudo.recvfrom(65535)
            received.append(data.decode("ascii"))
        values = [parse_packet(p).blendshapes["jawOpen"] for p in received]
        assert values == [0, 1, 2, 3, 4]

        # 4) 재생 종료 후 패스스루 복귀
        deadline = time.time() + 3.0
        while proxy.mode is not Mode.PASSTHROUGH and time.time() < deadline:
            time.sleep(0.02)
        assert proxy.mode is Mode.PASSTHROUGH
    finally:
        proxy.stop()
        phone.close()
        warudo.close()
```

- [ ] **Step 2: 테스트 실행**

실행: `python -m pytest tests/test_proxy_e2e.py -v`
예상: PASS. FAIL이면 원인을 파악하고 해당 모듈(프록시/플레이어)을 수정한다.

- [ ] **Step 3: 전체 테스트 실행**

실행: `python -m pytest tests/ -v`
예상: 전부 PASS

- [ ] **Step 4: 커밋**

```bash
rtk git add tests/test_proxy_e2e.py
rtk git commit -m 'test: 가짜 아이폰-Warudo E2E 시나리오'
```

---

### Task 10: GUI + 엔트리포인트

**Files:**
- Create: `arkit_recorder/gui.py`
- Create: `main.py`

**Interfaces:**
- Consumes: `FaceProxy`(Task 7~8), `Config`/`load_config`(Task 3)
- Produces:
  - `run_gui(proxy: FaceProxy, config: Config) -> None` — tkinter 메인루프 (블로킹)
  - `main.py` — config 로드 → 프록시 시작 → GUI 실행 → 종료 시 프록시 정리

- [ ] **Step 1: gui.py 구현**

tkinter는 자동 테스트가 어려우므로 이 태스크는 구현 후 수동 스모크로 검증한다.

```python
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
```

- [ ] **Step 2: main.py 구현**

```python
# main.py
from pathlib import Path

from arkit_recorder.config import load_config
from arkit_recorder.gui import run_gui
from arkit_recorder.proxy import FaceProxy

BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    config = load_config(BASE_DIR / "config.json")
    proxy = FaceProxy(config, BASE_DIR)
    proxy.start()
    try:
        run_gui(proxy, config)
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 전체 테스트 회귀 확인**

실행: `python -m pytest tests/ -v`
예상: 전부 PASS

- [ ] **Step 4: 수동 스모크 (GUI)**

실행: `python main.py`
확인 항목:
1. 창이 뜨고 "수신: 없음 (아이폰 미연결)" 표시
2. `config.json`이 생성됨 (기본값)
3. 별도 터미널에서 가짜 폰 실행:
   `python -c "import socket,time; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); [s.sendto(b'jawOpen-50|trackingStatus-1|=|head#0,0,0|',('127.0.0.1',49983)) or time.sleep(0.016) for _ in range(300)]"`
   실행 중 "수신: 60 Hz" 근처로 표시되는지
4. 수신 중 녹화 시작 → 정지 → 이름 입력 → 클립 목록에 나타나는지
5. 클립 선택 → 재생 → 모드 "재생 중" → 종료 후 "패스스루" 복귀
6. 루프 체크 → 재생 → 정지 버튼으로 중단되는지

- [ ] **Step 5: 커밋**

```bash
rtk git add arkit_recorder/gui.py main.py
rtk git commit -m 'feat: tkinter GUI와 엔트리포인트'
```

---

## 실기 검증 (구현 완료 후, 사용자 진행)

1. Warudo 씬의 iFacialMocap Receiver 포트를 49983 → 49984로 변경
2. `python main.py` 실행 (아이폰 앱 설정은 그대로)
3. 아바타가 평소처럼 움직이는지 (패스스루), 지연 체감 없는지
4. 녹화 → 재생: 아바타가 녹화된 표정을 재현하는지
5. 아이폰을 끈 상태에서 재생: 클립만으로 아바타가 움직이는지
6. 루프 재생: 경계에서 표정 점프가 거슬리지 않는지
