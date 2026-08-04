import json

import pytest

from arkit_recorder.protocol import parse_packet
from arkit_recorder.timeline import (
    TimelineData,
    activity_curve,
    blendshape_curve,
    blendshape_names,
    frame_activity,
    frame_index_at,
    load_timeline,
    save_frames,
    trim,
)


def P(**shapes):
    body = "|".join(f"{k}-{v}" for k, v in shapes.items())
    return body + "|trackingStatus-1|=|head#0,0,0|"


def write_clip(path, entries):
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )


def make_data(pairs):
    return TimelineData(frames=list(pairs), duration_ms=pairs[-1][0] if pairs else 0)


def test_load_timeline_skips_corrupt(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(
        '{"t": 0, "d": "a-1|=|head#0,0,0|"}\n'
        "garbage\n"
        '{"t": 100, "d": "a-2|=|head#0,0,0|"}\n',
        encoding="utf-8",
    )
    data = load_timeline(path)
    assert len(data.frames) == 2
    assert data.duration_ms == 100


def test_load_timeline_empty(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text("", encoding="utf-8")
    data = load_timeline(path)
    assert data.frames == []
    assert data.duration_ms == 0


def test_frame_activity_common_keys_only():
    a = parse_packet(P(jawOpen=10, smile=50, onlyA=99))
    b = parse_packet(P(jawOpen=30, smile=45, onlyB=77))
    # 공통 키: jawOpen |30-10|=20, smile |45-50|=5 -> 25. trackingStatus/단독 키 제외
    assert frame_activity(a, b) == pytest.approx(25.0)
    assert frame_activity(None, b) == 0.0
    assert frame_activity(a, None) == 0.0


def test_activity_curve():
    data = make_data([
        (0, P(jawOpen=0)),
        (100, P(jawOpen=40)),
        (200, "not parseable"),
        (300, P(jawOpen=100)),
    ])
    curve = activity_curve(data)
    assert curve[0] == (0, 0.0)
    assert curve[1] == (100, pytest.approx(40.0))
    assert curve[2] == (200, 0.0)              # 파싱 불가 -> 0.0
    assert curve[3] == (300, pytest.approx(60.0))  # 직전 유효 프레임(t=100) 대비


def test_blendshape_curve_and_names():
    data = make_data([
        (0, P(jawOpen=1, smile=2)),
        (50, "broken"),
        (100, P(jawOpen=3)),
    ])
    assert blendshape_curve(data, "jawOpen") == [(0, 1), (100, 3)]
    assert blendshape_curve(data, "smile") == [(0, 2)]
    assert blendshape_names(data) == ["jawOpen", "smile"]  # trackingStatus 제외, 정렬


def test_frame_index_at():
    data = make_data([(0, "x"), (100, "y"), (250, "z")])
    assert frame_index_at(data, -5) == 0
    assert frame_index_at(data, 0) == 0
    assert frame_index_at(data, 99) == 0
    assert frame_index_at(data, 100) == 1
    assert frame_index_at(data, 260) == 2
    assert frame_index_at(TimelineData(frames=[], duration_ms=0), 50) == -1


def test_trim_rebases_time():
    data = make_data([(0, "a"), (100, "b"), (200, "c"), (300, "d")])
    out = trim(data, 100, 200)
    assert out == [(0, "b"), (100, "c")]
    assert trim(data, 250, 260) == []
    assert trim(data, 0, 300) == [(0, "a"), (100, "b"), (200, "c"), (300, "d")]


def test_save_frames_roundtrip(tmp_path):
    path = tmp_path / "out.jsonl"
    frames = [(0, "a-1|=|head#0,0,0|"), (100, "a-2|=|head#0,0,0|")]
    assert save_frames(frames, path) == 2
    data = load_timeline(path)
    assert data.frames == frames
