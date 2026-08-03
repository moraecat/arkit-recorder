# tests/test_protocol.py
import pytest

from arkit_recorder.protocol import Frame, parse_packet, serialize_frame

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
