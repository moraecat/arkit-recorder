# arkit-recorder v2.2 루프 표시 + 실시간 구간 + 일시정지 스크럽 설계

날짜: 2026-08-05
상태: 승인됨
기반: 2026-08-05-playback-ux-design.md (v2.1)

## 1. 목적 (실기 피드백 3건)

1. 루프 토글의 켜짐/꺼짐이 보이지 않음 → 체크 상태 시각화
2. 트림 구간 변경이 재생 중 반영되지 않음 → 실시간 반영
3. 재생 중 스크럽 시 일시정지로 전환, 놓으면 그 프레임으로 고정(일시정지 유지)

## 2. 루프 토글 시각화

`qt/app.py` DARK_QSS에 추가:

```
QPushButton:checked { background-color: #3d5a80; border-color: #4f9cf9; }
```

## 3. 실시간 구간 반영

### 3.1 ClipPlayer

- `set_range(start_ms: int, end_ms: int | None) -> None` — 재생 중 구간 변경
  (GUI 단일 작성자, int 대입은 GIL 원자적)
- `play()`는 시작 시 range 인자를 인스턴스 필드로 저장하고, 이후 루프가 필드를 참조:
  - **프레임 반복 중**: 각 프레임 송출 전 현재 `range_end`를 확인, 넘으면 그 바퀴 종료
    (루프면 되감기, 아니면 재생 종료). 바퀴의 프레임 목록은 시작 경계만 선필터하고
    끝 경계는 동적 확인 — **재생 중 끝을 늘리면 즉시 이어지고, 줄이면 즉시 끊김**
  - **되감기 시**: 현재 `range_start` 기준으로 프레임 목록 재계산, 비면 종료
  - base_ms 규칙은 v2.1 그대로 (바퀴 시작 경계 0이면 0, 아니면 첫 프레임 t)

### 3.2 FaceProxy / 위젯

- `update_playback_range(start_ms, end_ms) -> None` — PLAYING이고 플레이어가 있으면
  `set_range` 위임, 아니면 무시
- 위젯: 트림 마커 드래그(mouseMove)와 릴리즈에서 `update_playback_range(트림 구간)` 호출

## 4. 일시정지 스크럽

### 4.1 상태 모델

- 새 Mode는 추가하지 않는다. "일시정지"는 **SCRUBBING 모드 + 위젯의 paused 플래그**
  (킵얼라이브가 계속 돌아 마지막 프레임을 100ms 주기로 송출 → 아바타 고정,
  Warudo 타임아웃 방지)

### 4.2 FaceProxy 확장

- `begin_scrub()`: PLAYING에서도 True —
  1. 락: PLAYING이면 즉시 `_mode = SCRUBBING` (라이브 유출 창 없음 — 수신 차단 유지),
     스크럽 필드 초기화, 플레이어/스레드 참조 캡처
  2. 락 해제 후 `player.stop()` + 스레드 `join(timeout=1.0)` (조인 완료 후 반환 —
     이후 재생 프레임이 스크럽과 섞이지 않음. 락 밖 조인이므로 `_finish_playback`과
     데드락 없음)
  - PASSTHROUGH 기존 동작 유지, 그 외(RECORDING/SCRUBBING) False
- `_finish_playback`: 모드 복귀와 페이드백 설정을 모두 `if self._mode is Mode.PLAYING`
  분기 **안**으로 이동 — 스크럽 전환으로 종료된 경우 모드/페이드를 건드리지 않음
- `start_playback()`: 시작 허용 모드를 PASSTHROUGH **또는 SCRUBBING**으로 확장.
  SCRUBBING에서 시작하면 리드인을 라이브 대신 `_last_scrub_packet`으로 사용
  (고정 표정 → 재생 첫 프레임 크로스페이드). PASSTHROUGH 경유 없이 직전환
  (라이브 유출 창 없음)
- `end_scrub()` 무변경 (일시정지 해제 = 라이브 복귀 크로스페이드)

### 4.3 위젯 (TimelineWidget)

- `_paused: bool` 상태 추가. `is_paused() -> bool` 공개
- **press**: paused 상태면 begin_scrub 없이 드래그 재개. 아니면 기존 begin_scrub
  (이제 PLAYING에서도 성공 — 성공 시 킵얼라이브 시작)
- **release**: 스크럽이 PLAYING에서 시작됐거나 이미 paused였으면 → `_paused = True`,
  킵얼라이브 유지, end_scrub 호출 안 함. 그 외 기존(킵얼라이브 정지 + end_scrub)
- (판정) 스크럽 시작이 PLAYING이었는지는 press 시점에 `proxy.mode` 확인으로 기억
- `_resend_scrub` 가드: 드래그 중이거나 paused면 재전송 (paused 고정의 핵심)
- `release_pause(end: bool) -> None`: paused 해제 공통 —
  킵얼라이브 정지, `_paused = False`, `end=True`면 `proxy.end_scrub()` 호출
  (정지 버튼용), `end=False`면 모드 유지 (재생 재개용 — start_playback이 전환)

### 4.4 메인 윈도우

- [재생] (`_on_play`): paused면 `release_pause(end=False)` 후 기존 `_playback_range()`로
  `start_playback` (플레이헤드=스크럽 위치부터). busy 가드는 "SCRUBBING이지만 paused"를
  예외로 허용
- [정지] (`_on_stop`): paused면 `release_pause(end=True)`만 하고 종료 (라이브 복귀).
  재생 중이면 기존 동작
- poll: paused면 모드 라벨 "일시정지" 표시(오버라이드), 재생 버튼 활성·정지 버튼 활성.
  녹화/이름변경/삭제는 SCRUBBING과 동일하게 비활성 유지
- 클립 선택 변경 시 paused면 먼저 `release_pause(end=True)` (이전 클립 프레임 고정 해제)

## 5. 에러 처리

| 상황 | 동작 |
|------|------|
| begin_scrub의 조인 타임아웃(1초) | 그대로 진행 (플레이어는 stop 이벤트로 곧 종료, 최악 1프레임 중복) |
| paused 중 재생 클립과 다른 클립 선택 | release_pause(end=True) 후 새 클립 로드 |
| 재생 중 구간을 플레이헤드보다 뒤로 줄임 | 다음 프레임 확인에서 바퀴 종료 (루프: 되감기 / 비루프: 종료) |
| update_playback_range를 비재생 중 호출 | 무시 |

## 6. 테스트

- player: set_range로 끝 축소(즉시 종료)/확장(이어짐)/루프 되감기 반영 (fake clock)
- proxy: PLAYING에서 begin_scrub(모드 전환+재생 프레임 중단+라이브 차단 유지),
  SCRUBBING에서 start_playback(리드인=마지막 스크럽 프레임), _finish_playback이
  스크럽 전환 시 모드/페이드 불변, update_playback_range 위임/무시
- GUI(QSS, paused 상태 머신, 라벨)는 수동 스모크

## 7. 비범위

- 별도 일시정지 버튼, 재생 중 스크럽 후 자동 재개(놓으면 항상 일시정지)
- 구간 반복 횟수, 프레임 단위 스텝 이동
