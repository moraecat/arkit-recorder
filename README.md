# ARKit Recorder

아이폰 페이스 트래킹(iFacialMocap)의 **신호 자체를 녹화해뒀다가,
아이폰 없이 그대로 재생 송출**하는 상시 실행 UDP 프록시입니다.

트래킹 앱이 보내는 iFacialMocap 프로토콜 패킷을 원본 그대로 기록하고 원래
타이밍으로 다시 내보내는 방식이라, 특정 소프트웨어에 종속되지 않습니다 —
**iFacialMocap 프로토콜을 수신하는 어떤 툴로도 재생할 수 있습니다**
([Warudo](https://warudo.app), VSeeFace, VNyan, iFacialMocap PC 소프트웨어 등).
방송 중 자리비움 루프, 반복 연기 재생 용도로 만들어졌습니다.

## 동작 원리

```
[패스스루 / 녹화]
아이폰 앱 --UDP--> ARKit Recorder :49983 --그대로 전달--> 수신 앱 :49984
                        |
                        +--> (녹화 중) clips/이름.jsonl 무손실 기록

[재생 / 스크럽]
클립 --> ARKit Recorder --원래 타이밍대로--> 수신 앱 :49984
         (이 동안 라이브 패킷은 차단, 종료 시 크로스페이드 복귀)
```

iFacialMocap 프로토콜 수신부는 순수 UDP 수신이라 보내는 쪽이 아이폰인지
이 프로그램인지 구분하지 않습니다. 패킷을 파싱·가공 없이 원본 그대로 저장하므로
재생 충실도는 100%이고, 52개 ARKit 블렌드쉐이프 + 머리 위치/회전 + 시선이
모두 보존됩니다.

## 기능

- **패스스루**: 평상시엔 투명한 프록시 (아이폰 → 수신 앱)
- **녹화**: 버튼 즉시 정지, 무손실 JSONL 저장, 실시간 활동량 파형
- **재생**: 구간(트림) 재생/루프, 재생 중 실시간 구간 변경, 시작/루프/복귀 크로스페이드
- **타임라인**: 활동량·블렌드쉐이프(52종) 곡선, 스크럽(드래그하면 아바타가 실시간으로
  따라옴), 비파괴 트리밍
- **일시정지**: 타임라인 클릭/스크럽 릴리즈 = 해당 프레임 고정 (킵얼라이브로 수신 앱
  타임아웃 방지), 상태 버튼으로 표시/조작
- **클립 관리**: 이름 변경/삭제/길이 표시, 설정 GUI (포트·크로스페이드 즉시 적용)

## 사용법

### 1회 설정

수신 앱의 iFacialMocap 수신 포트를 **49983 → 49984로 변경**하세요
(예: Warudo는 iFacialMocap Receiver 에셋의 Port 속성). 아이폰 앱 설정(PC IP 입력)은
그대로 둡니다. 수신 앱의 포트를 바꿀 수 없는 경우, 이 프로그램의 설정에서
전달 포트를 수신 앱에 맞게 조정할 수도 있습니다 (수신 포트 49983과만 다르면 됩니다).

### 실행

배포된 `arkit-recorder.exe`를 실행하거나:

```
pip install -r requirements.txt
python main.py
```

첫 실행 시 exe(또는 main.py) 옆에 `config.json`과 `clips/` 폴더가 생성됩니다.
프로그램이 꺼져 있으면 트래킹이 수신 앱에 전달되지 않으므로 방송 중 상시 실행이
전제입니다.

## 요구사항

- Windows, Python 3.11+ (exe는 파이썬 불필요)
- PySide6 (GUI). 코어 로직은 표준 라이브러리만 사용
- iFacialMocap 프로토콜로 송신하는 트래킹 앱 (iFacialMocap, FaceMotion3D 등)

## 개발

```
python -m pytest tests/ -v        # 테스트 (92개, PySide6 불필요)
pyinstaller --onefile --windowed --name arkit-recorder main.py   # exe 빌드
```

설계 문서는 `docs/superpowers/specs/`에 있습니다.

## 라이선스

[MIT](LICENSE)
