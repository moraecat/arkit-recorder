# arkit-recorder Qt UI 현대화 + 타임라인 설계

날짜: 2026-08-05
상태: 승인됨
기반: 2026-08-04-arkit-recorder-design.md (v1), 2026-08-04-clip-settings-design.md (v1.1)

## 1. 목적

tkinter GUI를 stream-manager 전례를 따라 PySide6 다크 대시보드로 재구축하고,
클립 타임라인(곡선 시각화 + 스크러빙 + 트리밍 + 녹화 실시간 표시)을 추가한다.

결정 사항:
- 3D 블렌드쉐이프 프리뷰는 하지 않는다 (사용자 결정). 스크럽 시 Warudo로 프레임을
  직접 송출해 아바타가 그 표정을 취하게 하는 것이 실용적 대체다.
- 표준 라이브러리 전용 원칙은 폐기한다. 의존성: PySide6 (qasync 불필요 —
  이 프로젝트는 asyncio가 없고 스레드 기반이라 QTimer 폴링으로 충분).

## 2. 구조

```
requirements.txt          PySide6>=6.6 (신설)
main.py                   qt 앱 실행으로 변경
arkit_recorder/
  timeline.py             타임라인 데이터 (순수 로직, pytest 대상)
  qt/
    __init__.py
    app.py                QApplication 생성 + 다크 테마(QSS) + run_app()
    main_window.py        대시보드 레이아웃/배선 (QTimer 폴링)
    timeline_widget.py    QPainter 커스텀 타임라인 위젯
    settings_dialog.py    Qt판 설정 다이얼로그
  gui.py                  삭제
  settings_dialog.py      삭제 (검증 로직은 qt/settings_dialog.py로 이식)
```

코어(protocol/proxy/recorder/player/clips/config)는 §5의 최소 확장 외에 무변경.
`arkit_recorder/qt/` 밖의 모듈은 PySide6를 import하지 않는다
(코어 테스트가 PySide6 없이도 돌아야 함).

## 3. 화면 구성 (단일 창 다크 대시보드)

- **상단 바** (가로 1행): 수신 상태(Hz/끊김/미연결, 색상), 모드, 전달 대상, [설정] 버튼
- **좌측 패널** (고정폭 ~280px): 클립 목록(QListWidget, `이름 — 12.3초`),
  [녹화 시작/정지] [재생] [정지] [루프 체크] [이름 변경] [삭제]
- **우측 (확장)**: 타임라인 위젯 + 곡선 선택 콤보박스 + [구간을 새 클립으로 저장]
- 다크 테마: Fusion 스타일 + QSS 상수(qt/app.py 내). 한글 UI 문자열, 이모지 금지
- 폴링: QTimer 200ms — 상태 갱신, 재생 플레이헤드, 녹화 실시간 파형은 100ms

기존 tkinter GUI의 모든 동작(녹화 이름 저장 흐름, 재생/루프, 이름 변경/삭제
검증 메시지, 설정 검증/적용/저장, 재생 중 버튼 비활성)은 동일하게 유지된다.

## 4. 타임라인

### 4.1 데이터 (`timeline.py`, 순수 로직)

```python
@dataclass
class TimelineData:
    frames: list[tuple[int, str]]     # (t_ms, packet) — ClipPlayer.load와 동일 파싱
    duration_ms: int                  # 마지막 프레임 t (빈 클립이면 0)

def load_timeline(path: Path) -> TimelineData          # 손상 라인 스킵 (player와 동일)
def activity_curve(data: TimelineData) -> list[tuple[int, float]]
    # 각 프레임의 활동량 = 직전 프레임과의 블렌드쉐이프 값 차 절대값 합 (0번째는 0.0)
    # trackingStatus 키는 활동량 계산에서 제외, 파싱 불가 프레임은 활동량 0.0
def blendshape_curve(data: TimelineData, name: str) -> list[tuple[int, int]]
    # 해당 키가 없는 프레임은 건너뜀
def blendshape_names(data: TimelineData) -> list[str]
    # 전 프레임에 등장한 키의 합집합, 정렬. trackingStatus 제외
def frame_index_at(data: TimelineData, t_ms: int) -> int
    # t_ms 이하의 가장 가까운 프레임 인덱스 (이진 탐색). 빈 클립이면 -1
def trim(data: TimelineData, start_ms: int, end_ms: int) -> list[tuple[int, str]]
    # [start, end] 구간 프레임을 t가 0부터 시작하도록 재정렬해 반환
    # (첫 프레임 t를 0으로 평행이동). 구간에 프레임 없으면 빈 리스트
def save_frames(frames: list[tuple[int, str]], path: Path) -> int
    # JSONL 저장 ({"t": ..., "d": ...}), 프레임 수 반환
```

### 4.2 위젯 동작 (`timeline_widget.py`)

- **그리기**: 배경 눈금(초 단위), 곡선(활동량 또는 선택 블렌드쉐이프), 플레이헤드
  (재생 위치), 트림 마커 2개(시작/끝, 드래그 핸들), 트림 구간 하이라이트
- **좌클릭 드래그 = 스크러빙**:
  - 마우스 다운: `proxy.begin_scrub()` 성공 시 스크럽 모드 (실패 시 무시 —
    녹화/재생 중)
  - 드래그: 위치 → `frame_index_at` → **프레임 인덱스가 바뀐 경우에만**
    `proxy.scrub_frame(packet)` 송출
  - 마우스 업: `proxy.end_scrub()` — 라이브 가용 시 크로스페이드 복귀
- **트림 마커 드래그**: 마커 핸들(상단 삼각형) 근처에서만 잡힘. 곡선 영역
  드래그(스크럽)와 겹치지 않게 마커는 상단 12px 밴드에서만 잡힌다
- **재생 연동**: 재생 시작 전 클릭으로 시작 위치 지정 가능 —
  [재생]은 `start_playback(..., start_ms=플레이헤드 위치)` (플레이헤드가 클립
  끝이면 0부터). 재생 중 폴링으로 `player.position_ms` 반영
- **녹화 실시간**: 녹화 중에는 선택 클립 대신 recorder의 라이브 파형
  (`live_wave()`)을 그린다. 스크럽/트림 비활성

### 4.3 클립 선택 연동

- 클립 목록 선택 시 `load_timeline`으로 로드해 타임라인 표시, 곡선 콤보박스를
  `["활동량"] + blendshape_names`로 갱신
- 이름 변경/삭제/트림 저장 후 목록 갱신 (기존 흐름 유지). 삭제된 클립이 표시
  중이면 타임라인 비움

### 4.4 트리밍 저장

- [구간을 새 클립으로 저장] → 이름 입력(QInputDialog) → 이름 검증 후
  `save_frames(trim(...), 검증이 반환한 경로)` → 목록 갱신
- 이름 검증은 `clips.py`에 `validate_clip_name(clips_dir, name) -> Path` 헬퍼로
  추출한다 (빈 이름/밑줄/경로 문자/중복 검사 후 최종 경로 반환, 위반 시 한글
  ValueError). 기존 `rename_clip`도 이 헬퍼를 재사용하도록 리팩토링 (동작 불변)
- 트림 구간이 비었으면 경고. 원본은 항상 보존 (비파괴)

## 5. 코어 최소 확장

### 5.1 `ClipPlayer`

- `position_ms: int` 속성 — 재생 중 현재 프레임 t_ms (재생 전 0, 종료 후 마지막 값)
- `play(loop=False, lead_in_packet=None, start_ms=0)` — start_ms 이상 첫 프레임부터
  재생. 타이밍은 `t_ms - start_ms` 기준으로 재계산. 리드인 크로스페이드의 진행
  기준도 동일하게 상대화. 루프는 항상 클립 전체(0부터)로 되감음
- `FaceProxy.start_playback(clip_path, loop, start_ms=0)`로 전달

### 5.2 `ClipRecorder` — 실시간 파형 링버퍼

- `feed()`에서 패킷을 파싱해 직전 프레임 대비 활동량(블렌드쉐이프 차 절대값 합,
  trackingStatus 제외)을 계산, `(t_ms, activity)`를 `deque(maxlen=36000)`에 축적
  (60fps 10분). 파싱 불가 패킷은 activity 0.0
- `live_wave() -> list[tuple[int, float]]` — 스냅샷 반환 (GUI 폴링용)
- `start()` 시 링버퍼 초기화. 파일 기록 동작은 무변경

### 5.3 `FaceProxy` — 스크럽

- `Mode.SCRUBBING` 추가. `_recv_loop`의 라이브 차단 조건을
  `mode in (PLAYING, SCRUBBING)`으로 확장
- `begin_scrub() -> bool` — PASSTHROUGH에서만 성공(모드 전환), 아니면 False
- `scrub_frame(packet: str) -> None` — SCRUBBING 모드에서만 송출.
  trackingStatus-0 프레임은 송출 생략 (player와 동일 규칙).
  마지막 송출 패킷을 기억 (복귀 페이드용)
- `end_scrub() -> None` — PASSTHROUGH 복귀. 라이브 가용 + 마지막 송출 프레임
  존재 시 기존 `_fade_back_from/_fade_back_until` 메커니즘으로 크로스페이드 복귀
  (재생 종료와 동일). 라이브 부재 시 마지막 스크럽 표정 유지
- 스크럽 중 녹화/재생 시작은 기존 가드(PASSTHROUGH 전용)로 자연 차단됨

## 6. 에러 처리

| 상황 | 동작 |
|------|------|
| 녹화/재생 중 스크럽 시도 | begin_scrub False, 위젯 무반응 |
| 트림 구간에 프레임 없음 | 경고 대화상자, 저장 안 함 |
| 트림 저장 이름 검증 실패 | clips와 동일 한글 메시지 경고 |
| 빈 클립 타임라인 | "프레임 없음" 안내 텍스트 표시 |
| 표시 중 클립 삭제 | 타임라인 비움 |
| PySide6 미설치 실행 | main.py에서 ImportError 안내 후 종료 (pip install 안내) |

## 7. 테스트 전략

- pytest (PySide6 불필요, 코어만): timeline.py 전 함수(곡선/이름/이진탐색/트림
  재정렬/저장), player position_ms·start_ms(fake clock), recorder 링버퍼
  (활동량 수치), proxy 스크럽(실 UDP — begin/scrub_frame 송출/차단/end 페이드백)
- Qt 위젯/창은 수동 스모크 (기존 방침). GUI 실행 금지 원칙 유지 (구현 에이전트)
- 기존 54개 테스트 회귀 없음 필수

## 8. 배포

- PyInstaller `--onefile --windowed` 재빌드. PySide6 포함으로 exe 약 40~50MB 예상
- tkinter 관련 코드 제거로 hiddenimports 이슈 없음 확인

## 9. 비범위

- 3D 블렌드쉐이프 프리뷰 (취소 결정)
- 다중 곡선 동시 표시, 키프레임 편집, 클립 이어붙이기, 되돌리기(undo)
- 시스템 트레이, qasync, 자동 GUI 테스트(pytest-qt)
- 타임라인 줌/팬 (전체 길이 고정 표시)
