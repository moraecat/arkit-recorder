from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Frame:
    blendshapes: dict[str, int] = field(default_factory=dict)
    head_rotation: tuple[float, float, float] | None = None
    head_position: tuple[float, float, float] | None = None
    left_eye: tuple[float, float, float] | None = None
    right_eye: tuple[float, float, float] | None = None


def parse_packet(text: str) -> Frame | None:
    # Warudo iFacialMocapClient와 동일 규칙: 공백 제거, 유일한 '='로 분리
    compact = text.replace(" ", "")
    if compact.count("=") != 1:
        return None
    bs_part, head_part = compact.split("=", 1)
    frame = Frame()
    for token in bs_part.split("|"):
        name, sep, value = token.partition("-")
        if not sep or not name:
            continue
        try:
            frame.blendshapes[name] = int(value)
        except ValueError:
            continue
    for token in head_part.split("|"):
        name, sep, nums = token.partition("#")
        if not sep:
            continue
        try:
            values = tuple(float(v) for v in nums.split(","))
        except ValueError:
            continue
        if name == "head":
            if len(values) >= 6:
                frame.head_rotation = values[0:3]
                frame.head_position = values[3:6]
            elif len(values) >= 3:
                frame.head_rotation = values[0:3]
        elif name == "leftEye" and len(values) >= 3:
            frame.left_eye = values[0:3]
        elif name == "rightEye" and len(values) >= 3:
            frame.right_eye = values[0:3]
    return frame


def lerp_angle(a: float, b: float, t: float) -> float:
    delta = ((b - a + 180.0) % 360.0) - 180.0
    return a + delta * t


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend_tuple(a, b, t, angular):
    if a is None:
        return b
    if b is None:
        return a
    fn = lerp_angle if angular else _lerp
    return tuple(fn(x, y, t) for x, y in zip(a, b))


def blend_frames(a: Frame, b: Frame, t: float) -> Frame:
    out = Frame()
    for name, vb in b.blendshapes.items():
        va = a.blendshapes.get(name)
        out.blendshapes[name] = vb if va is None else round(_lerp(va, vb, t))
    for name, va in a.blendshapes.items():
        if name not in out.blendshapes:
            out.blendshapes[name] = va
    out.head_rotation = _blend_tuple(a.head_rotation, b.head_rotation, t, angular=True)
    out.head_position = _blend_tuple(a.head_position, b.head_position, t, angular=False)
    out.left_eye = _blend_tuple(a.left_eye, b.left_eye, t, angular=True)
    out.right_eye = _blend_tuple(a.right_eye, b.right_eye, t, angular=True)
    return out


def serialize_frame(frame: Frame) -> str:
    parts = [f"{name}-{value}" for name, value in frame.blendshapes.items()]
    tokens = []
    if frame.head_rotation is not None:
        nums = list(frame.head_rotation)
        if frame.head_position is not None:
            nums.extend(frame.head_position)
        tokens.append("head#" + ",".join(str(v) for v in nums))
    if frame.right_eye is not None:
        tokens.append("rightEye#" + ",".join(str(v) for v in frame.right_eye))
    if frame.left_eye is not None:
        tokens.append("leftEye#" + ",".join(str(v) for v in frame.left_eye))
    return "|".join(parts) + "|=|" + "|".join(tokens) + "|"
