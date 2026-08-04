import json

import pytest

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


def test_stop_from_another_thread(tmp_path):
    import threading
    import time as real_time

    path = tmp_path / "c.jsonl"
    write_clip(path, [
        {"t": i * 10, "d": f"a-{i}|trackingStatus-1|=|head#0,0,0|"}
        for i in range(500)
    ])
    sent = []
    player = ClipPlayer(send=sent.append)  # 실제 시계/슬립 사용
    player.load(path)
    thread = threading.Thread(target=player.play)
    thread.start()
    real_time.sleep(0.1)
    player.stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert not player.is_playing
    assert 0 < len(sent) < 500  # 도중에 끊겼음


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

    # 루프 크로스페이드를 끄고 순수 되감기 동작만 검증
    player = make_player(clock, send, crossfade_loop_ms=0)
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
