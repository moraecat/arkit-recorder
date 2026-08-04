# arkit-recorder 클립 관리 + 설정 기능 설계

날짜: 2026-08-04
상태: 승인됨
기반: 2026-08-04-arkit-recorder-design.md (v1 스펙)

## 1. 목적

v1에서 빠져 있던 두 기능을 추가한다.

- 클립 관리: GUI에서 클립 이름 변경, 삭제, 길이 표시
- 설정: GUI에서 포트(수신/전달)와 크로스페이드 시간을 변경하고 즉시 적용

## 2. 클립 관리

### 2.1 모듈: `arkit_recorder/clips.py` (신설)

```python
@dataclass
class ClipInfo:
    name: str            # 확장자 제외 파일명
    path: Path
    duration_s: float | None   # 마지막 유효 라인의 t(ms) / 1000, 실패 시 None
    size_bytes: int

def list_clips(clips_dir: Path) -> list[ClipInfo]
def rename_clip(clips_dir: Path, old_name: str, new_name: str) -> Path
def delete_clip(path: Path) -> None
```

- `list_clips`: `*.jsonl` 중 밑줄(`_`) 시작 파일 제외, 이름 오름차순 정렬.
  길이는 파일 끝 4KB만 읽어 마지막 비어있지 않은 라인을 JSON 파싱해 `t`를 얻는다
  (t는 단조증가이므로 마지막 라인이 총 길이). 파싱 실패/빈 파일이면 `duration_s = None`.
  디렉토리가 없으면 빈 리스트.
- `rename_clip` 검증 (위반 시 `ValueError`, 메시지는 한글):
  - 새 이름이 빈 문자열(공백 제거 후)
  - 새 이름이 밑줄(`_`)로 시작
  - 같은 이름의 클립이 이미 존재
  - 원본이 존재하지 않음
  통과 시 `old.jsonl` → `new.jsonl` rename, 새 Path 반환.
- `delete_clip`: 파일 삭제. 재생 중인 클립이어도 안전하다 —
  ClipPlayer.load()는 파일 전체를 메모리에 올린 뒤 닫으므로 핸들이 남지 않는다.
  삭제 후에도 진행 중인 재생은 메모리 사본으로 계속된다 (허용 동작).

### 2.2 GUI 변경 (재생부)

- 목록 항목 표시: `이름 — 12.3초` (duration_s가 None이면 `이름 — ?`)
- 목록 아래 버튼 행에 [이름 변경] [삭제] 추가
  - 이름 변경: 선택 항목에 대해 `simpledialog.askstring` → `rename_clip` →
    실패 시 `messagebox.showwarning`(ValueError 메시지 표시), 성공 시 목록 갱신
  - 삭제: `messagebox.askyesno` 확인 후 `delete_clip` → 목록 갱신
- 재생 중(PLAYING)에는 [이름 변경] [삭제] 비활성 (기존 poll 패턴에 추가)
- 선택 항목이 없으면 두 버튼 클릭 시 `showinfo`로 선택 안내 (기존 재생 버튼과 동일 패턴)
- 재생/이름변경/삭제가 참조하는 이름은 표시 문자열이 아니라 ClipInfo.name을 쓴다
  (표시 형식 변경이 로직에 영향 없도록 목록 인덱스 → ClipInfo 매핑 유지)

## 3. 설정

### 3.1 `config.py` 확장

```python
def save_config(path: Path, config: Config) -> None   # indent=2 JSON 저장
```

### 3.2 `proxy.py` 확장: `apply_config`

```python
def apply_config(self, new: Config) -> str | None   # 성공 None, 실패 시 한글 오류 메시지
```

- **패스스루 모드에서만 허용.** 녹화/재생 중이면
  `"패스스루 상태에서만 설정을 적용할 수 있습니다"` 반환 (변경 없음).
- forward_host / forward_port: `_forward_addr` 즉시 교체.
- crossfade_live_ms / crossfade_loop_ms: `_config` 필드 갱신
  (다음 재생·복귀 페이드부터 반영).
- listen_port가 현재 바인드 포트와 다르면 리스너 재시작:
  1. 수신 스레드 정지 + 기존 소켓 close (스레드 join, 타임아웃 2초)
  2. 새 포트로 바인드 시도
  3. 실패 시 이전 포트로 재바인드(롤백)하고 오류 메시지 반환
     (롤백도 실패하면 bind_error 설정 후 오류 메시지 반환)
- 성공 시 `_config`의 필드를 새 값으로 **인플레이스 갱신**하고 None 반환.
  (main.py가 같은 Config 인스턴스를 FaceProxy와 run_gui에 공유하므로,
  객체 교체가 아니라 필드 갱신이어야 GUI 표시와 프록시 동작이 어긋나지 않는다.
  따라서 §3.3의 "기존 config 객체 필드 갱신"은 apply_config가 수행하는 것으로 충분)
- clips_dir은 GUI 설정 대상이 아니다 (config.json 직접 편집 유지).

수신 스레드 재시작을 위해 v1의 `start()`/`stop()`에서 리스너 부분을
`_start_listener()`/`_stop_listener()`로 추출한다 (동작 변화 없는 리팩토링).
`_stop_listener()`는 수신 스레드용 별도 stop 이벤트를 사용해 전체 `_stop_event`와
구분한다 (재시작 시 재생/전체 종료 상태를 건드리지 않기 위함).

### 3.3 GUI: 설정 다이얼로그 (`arkit_recorder/settings_dialog.py` 신설)

```python
def open_settings_dialog(parent, proxy, config, config_path) -> None
```

- 상태부에 [설정] 버튼 추가 → Toplevel 모달(grab_set) 다이얼로그
- 필드 5개 (Entry): 수신 포트, 전달 호스트, 전달 포트,
  크로스페이드 라이브(ms), 크로스페이드 루프(ms). 현재 config 값으로 초기화
- [저장] 클릭 시:
  1. 입력 검증 — 포트: 1~65535 정수, ms: 0 이상 정수, 호스트: 공백 제거 후 비어있지 않음.
     실패 시 `showwarning`, 다이얼로그 유지
  2. `proxy.apply_config(new_config)` — 오류 메시지 반환 시 `showwarning`, 다이얼로그 유지
  3. 성공 시 `save_config(config_path, new_config)` 후 기존 config 객체 필드를
     새 값으로 갱신(전달 대상 라벨 등 GUI 표시 일관성)하고 다이얼로그 닫힘
- [취소] 버튼: 변경 없이 닫힘
- 녹화/재생 중에도 다이얼로그는 열 수 있으나 저장은 apply_config가 거부한다

### 3.4 main.py

변경 없음 (config_path를 run_gui에 전달하는 시그니처 변경만:
`run_gui(proxy, config, config_path)`).

## 4. 에러 처리 요약

| 상황 | 동작 |
|------|------|
| 이름 변경 충돌/빈 이름/밑줄 시작 | ValueError 한글 메시지 → showwarning |
| 삭제 확인 취소 | 아무 것도 안 함 |
| 길이 계산 실패 (손상 파일) | 목록에 `?` 표시, 기능은 정상 |
| 설정 검증 실패 | showwarning, 다이얼로그 유지 |
| 녹화/재생 중 설정 저장 | apply_config 거부 메시지 표시 |
| 새 수신 포트 바인드 실패 | 이전 포트 롤백 + 오류 표시 |

## 5. 테스트

- `tests/test_clips.py`: list_clips 정렬/밑줄 제외/길이 계산(마지막 라인)/손상 파일 None/
  빈 디렉토리, rename_clip 정상·충돌·빈 이름·밑줄·원본 없음, delete_clip
- `tests/test_proxy.py` 추가:
  - apply_config로 forward 주소 변경 → 이후 패킷이 새 가짜 Warudo 소켓에 도착
  - listen_port 변경 → 새 포트로 보낸 패킷이 전달됨 (이전 포트는 닫힘)
  - 녹화 중/재생 중 apply_config 거부
  - 사용 중인 포트로 변경 시도 → 오류 반환 + 이전 포트로 계속 수신(롤백 검증)
  - 크로스페이드 값 변경 후 재생 시 새 값 사용
- 다이얼로그/GUI 배선은 수동 스모크 (기존 방침)

## 6. 비범위

- 클립 미리보기 재생, 정렬 옵션, 검색
- config.json 외부 변경 감시(핫 리로드)
- clips_dir 경로의 GUI 변경
- 재생/녹화 중 설정 적용 (거부가 사양)
