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
