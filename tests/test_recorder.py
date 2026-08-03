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
