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


def test_double_start_guard(tmp_path):
    # second start() must be a no-op: existing session is preserved
    rec = ClipRecorder(tmp_path / "_tmp.jsonl")
    rec.start()
    rec.feed("a-1|=|head#0,0,0|")
    rec.start()  # duplicate call — must not discard the ongoing session
    assert rec.is_recording
    rec.feed("a-2|=|head#0,0,0|")
    final = tmp_path / "clip.jsonl"
    count = rec.stop_and_save(final)
    assert count == 2
    lines = final.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


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
