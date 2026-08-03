# tests/test_protocol.py
import pytest

from arkit_recorder.protocol import Frame, parse_packet, serialize_frame
from arkit_recorder.protocol import blend_frames, lerp_angle

SAMPLE = (
    "mouthSmile_R-32|eyeBlink_L-5|trackingStatus-1|="
    "|head#28.98,-2.57,-6.64,-0.03,-0.1,-0.65"
    "|rightEye#6.02,2.44,0.25|leftEye#6.03,-1.66,-0.17|"
)


def test_parse_blendshapes():
    frame = parse_packet(SAMPLE)
    assert frame is not None
    assert frame.blendshapes == {
        "mouthSmile_R": 32, "eyeBlink_L": 5, "trackingStatus": 1,
    }
    assert list(frame.blendshapes) == ["mouthSmile_R", "eyeBlink_L", "trackingStatus"]


def test_parse_head_and_eyes():
    frame = parse_packet(SAMPLE)
    assert frame.head_rotation == (28.98, -2.57, -6.64)
    assert frame.head_position == (-0.03, -0.1, -0.65)
    assert frame.right_eye == (6.02, 2.44, 0.25)
    assert frame.left_eye == (6.03, -1.66, -0.17)


def test_parse_head_rotation_only():
    frame = parse_packet("a-1|=|head#1.0,2.0,3.0|")
    assert frame.head_rotation == (1.0, 2.0, 3.0)
    assert frame.head_position is None


def test_parse_negative_value():
    frame = parse_packet("browDown_L--3|=|head#0,0,0|")
    assert frame.blendshapes["browDown_L"] == -3


def test_parse_strips_spaces():
    frame = parse_packet("a-1 |= |head#1.0, 2.0,3.0|")
    assert frame.blendshapes["a"] == 1
    assert frame.head_rotation == (1.0, 2.0, 3.0)


def test_parse_invalid_equals_count():
    assert parse_packet("a-1|head#0,0,0|") is None      # '=' 없음
    assert parse_packet("a-1|=|b=2|head#0,0,0|") is None  # '=' 2개


def test_parse_skips_bad_tokens():
    frame = parse_packet("a-1|garbage|b-notanint|c-2|=|bad#x,y,z|head#0,0,0|")
    assert frame.blendshapes == {"a": 1, "c": 2}
    assert frame.head_rotation == (0.0, 0.0, 0.0)


def test_serialize_roundtrip():
    frame = parse_packet(SAMPLE)
    again = parse_packet(serialize_frame(frame))
    assert again == frame


def test_serialize_without_head_position():
    frame = Frame(blendshapes={"a": 1}, head_rotation=(1.5, 2.5, 3.5))
    again = parse_packet(serialize_frame(frame))
    assert again.head_rotation == (1.5, 2.5, 3.5)
    assert again.head_position is None


def test_lerp_angle_shortest_path():
    assert lerp_angle(350.0, 10.0, 0.5) == pytest.approx(360.0)
    assert lerp_angle(10.0, 350.0, 0.5) == pytest.approx(0.0)
    assert lerp_angle(0.0, 90.0, 0.5) == pytest.approx(45.0)


def test_blend_blendshapes_rounded():
    a = Frame(blendshapes={"smile": 0, "trackingStatus": 1})
    b = Frame(blendshapes={"smile": 100, "trackingStatus": 1})
    mid = blend_frames(a, b, 0.5)
    assert mid.blendshapes["smile"] == 50
    assert mid.blendshapes["trackingStatus"] == 1


def test_blend_one_sided_keys_kept():
    a = Frame(blendshapes={"onlyA": 10})
    b = Frame(blendshapes={"onlyB": 20})
    mid = blend_frames(a, b, 0.5)
    assert mid.blendshapes == {"onlyB": 20, "onlyA": 10}


def test_blend_head_rotation_shortest_path():
    a = Frame(head_rotation=(350.0, 0.0, 0.0), head_position=(0.0, 0.0, 0.0))
    b = Frame(head_rotation=(10.0, 0.0, 0.0), head_position=(1.0, 0.0, 0.0))
    mid = blend_frames(a, b, 0.5)
    assert mid.head_rotation[0] == pytest.approx(360.0)
    assert mid.head_position[0] == pytest.approx(0.5)


def test_blend_one_sided_head_kept():
    a = Frame(head_rotation=(1.0, 2.0, 3.0))
    b = Frame()
    assert blend_frames(a, b, 0.5).head_rotation == (1.0, 2.0, 3.0)
    assert blend_frames(b, a, 0.5).head_rotation == (1.0, 2.0, 3.0)


def test_blend_endpoints():
    a = Frame(blendshapes={"x": 0}, left_eye=(0.0, 0.0, 0.0))
    b = Frame(blendshapes={"x": 80}, left_eye=(10.0, 0.0, 0.0))
    assert blend_frames(a, b, 0.0).blendshapes["x"] == 0
    assert blend_frames(a, b, 1.0).blendshapes["x"] == 80
    assert blend_frames(a, b, 1.0).left_eye[0] == pytest.approx(10.0)
