# arkit-recorder v2.1 재생 UX 개선 설계

날짜: 2026-08-05
상태: 승인됨
기반: 2026-08-05-qt-ui-timeline-design.md (v2)

## 1. 목적 (실기 스모크 피드백 5건)

1. 녹화 정지가 이름 입력 확정 시점이 아니라 **버튼 클릭 시점**에 일어나야 한다
2. 스크럽 홀드 중 같은 값이라도 **주기 재전송**해야 한다 (Warudo 0.5초 무수신 = 트래킹 끊김)
3. 재생이 끝까지 간 뒤 다시 재생하면 **처음부터** 재생돼야 한다
4. 트림 구간이 설정되면 **그 구간에서만 재생/루프**해야 한다
5. 재생/정지/루프 컨트롤을 **음악 플레이어처럼 타임라인 아래 가운데 정렬**로

## 2. 녹화 정지 시점 분리

### 2.1 ClipRecorder (`recorder.py`)

```python
def finish(self) -> None   # 락 하: 파일 close, tmp 유지 (_file=None). 미녹화면 무시
def save_to(self, final_path: Path) -> int
    # finish 이후 호출 전제. tmp를 final_path로 rename, frame_count 반환.
    # tmp가 없으면 0 반환. 파형 버퍼는 여기서 초기화 (기존 stop_and_save와 동일)
```

- 기존 `stop_and_save(final_path)`는 `finish()` + `save_to()` 조합으로 재구현 (동작 불변)
- `discard()`는 기존 그대로 (finish 이후에도 tmp unlink 동작)
- `finish()` 후 `feed()`는 기존 가드(_file None)로 무시됨

### 2.2 FaceProxy (`proxy.py`)

```python
def finish_recording(self) -> None   # 락 하: RECORDING이면 recorder.finish() + PASSTHROUGH 복귀
def save_recording(self, name: str) -> Path   # recorder.save_to(clips_dir/name.jsonl)
def discard_recording(self) -> None  # recorder.discard()
```

- 기존 `stop_recording(name)`은 `finish_recording()` + `save_recording(name)` 조합으로
  재구현 (시그니처·동작 불변, 기존 테스트 무수정 통과)

### 2.3 GUI (`qt/main_window.py` `_on_record`)

- RECORDING 분기: 즉시 `finish_recording()` + 버튼 텍스트 "녹화 시작" 복원 → 이름 루프:
  1. `QInputDialog.getText` — 확정 시 `validate_clip_name` 검증 (실패: 경고 후 재입력 루프)
     → `save_recording(name.strip())` → 목록 갱신
  2. 취소/빈 이름 시 `QMessageBox.question("녹화를 저장하지 않고 버릴까요?")` —
     예: `discard_recording()` 종료, 아니오: 이름 다이얼로그 재표시

## 3. 스크럽 홀드 킵얼라이브

- `TimelineWidget`에 `_keepalive` QTimer(100ms): 스크럽 드래그 중이고 마지막 송출
  인덱스가 유효하면 해당 프레임 패킷을 `proxy.scrub_frame()`으로 재전송
- 시작: `begin_scrub()` 성공 직후. 정지: `mouseReleaseEvent`
- 근거: Warudo iFacialMocapClient는 수신 즉시 LastReceivedTime을 갱신하고 내용 중복
  제거는 파싱 단계에서만 하므로, 동일 패킷 재전송으로 타임아웃이 방지된다 (디컴파일 확인)

## 4. 구간 재생/루프 + 종료 후 처음부터

### 4.1 ClipPlayer (`player.py`)

```python
def play(self, loop=False, lead_in_packet=None, start_ms=0,
         range_start_ms=0, range_end_ms=None) -> None
```

- 재생 구간 = `[range_start_ms, range_end_ms]` (range_end_ms None이면 클립 끝).
  첫 바퀴는 `max(start_ms, range_start_ms)` 이상 ~ 구간 끝의 프레임.
  **루프 되감기는 구간 시작(range_start_ms)부터 구간 끝까지** (v2의 "항상 0부터"를 대체
  — 단 기본 인자에서는 range_start_ms=0이므로 기존 동작·기존 테스트와 동일)
- 타이밍/크로스페이드 진행 기준(base_ms): 각 바퀴에서 **시작 경계가 0이면 base=0,
  0보다 크면 그 바퀴 첫 프레임의 t** (v2 규칙의 일반화 — 기본 인자에서는 첫 바퀴
  base=0, 루프 바퀴 base=0으로 기존 테스트와 완전 동일. 구간 지정 시에만 구간 첫
  프레임 기준 상대 타이밍)
- 구간에 프레임이 없으면 즉시 반환 (기존 빈 클립과 동일)

### 4.2 FaceProxy

- `start_playback(clip_path, loop, start_ms=0, range_start_ms=0, range_end_ms=None)`
  — player.play로 전달 (반환값 의미 불변)

### 4.3 GUI

- [재생]: 트림 구간을 재생 범위로 전달. `start_ms`는 플레이헤드가 구간 안
  (`trim_start <= playhead < trim_end`)이면 플레이헤드, 아니면 `trim_start`
- **자연 종료 시** (poll에서 PLAYING → 비PLAYING 전이 감지 + 정지 버튼 미사용):
  플레이헤드를 `trim_start`로 리셋 → 다시 [재생]하면 구간 처음부터
- **정지 버튼으로 멈춘 경우**: 플레이헤드 유지 (이어 재생 가능)
  - 구현: `_on_stop`이 플래그(`_stopped_by_user`)를 세우고, poll의 전이 감지에서
    플래그가 있으면 리셋 생략 후 플래그 클리어

## 5. 음악 플레이어식 컨트롤 바

- 타임라인 위젯 바로 아래에 QHBoxLayout, `addStretch(1)` 양쪽으로 가운데 정렬:
  [재생] [정지] [루프 토글]
- 아이콘: Qt 표준 `QStyle.StandardPixmap.SP_MediaPlay` / `SP_MediaStop`,
  루프는 `setCheckable(True)` 토글 버튼(텍스트 "루프"). 이모지 사용 금지
- 좌측 패널에서 재생/정지/루프 제거 — 남는 것: 클립 목록, [녹화 시작/정지],
  [이름 변경] [삭제]
- 버튼 상태 규칙(poll)은 기존과 동일: busy(PLAYING/SCRUBBING) 시 재생 비활성,
  정지는 PLAYING에서만 활성, 녹화 중 재생 비활성

## 6. 에러 처리

| 상황 | 동작 |
|------|------|
| 이름 검증 실패 (저장 시) | 경고 후 이름 다이얼로그 재표시 (녹화 데이터 유지) |
| 버리기 확인 "아니오" | 이름 다이얼로그 재표시 |
| 구간에 프레임 없음 (재생) | start_playback 0 반환 → 기존 경고 다이얼로그 |
| finish 없이 save_to 호출 | tmp 부재 시 0 반환 (방어) |

## 7. 테스트

- recorder: finish 후 feed 무시/tmp 유지, save_to rename/카운트, stop_and_save 동작 불변
- player: 구간 재생(범위 밖 프레임 미송출), 구간 루프(되감기가 range_start로),
  기본 인자 시 기존 동작 (기존 테스트 무수정)
- proxy: finish/save/discard_recording, stop_recording 호환, start_playback 구간 전달
- GUI (킵얼라이브·컨트롤 바·리셋 플래그)는 수동 스모크

## 8. 비범위

- 일시정지(pause) 버튼, 시크 중 재생 유지, 구간 반복 횟수 설정
- 자동 이름 저장 (취소 정책은 "버리기 확인"으로 확정)
