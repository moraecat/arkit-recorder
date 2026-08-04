import json as jsonlib
import socket
import time
from pathlib import Path

import pytest

from arkit_recorder.config import Config
from arkit_recorder.protocol import parse_packet
from arkit_recorder.proxy import FaceProxy, Mode

PACKET = "a-1|trackingStatus-1|=|head#0,0,0|"


@pytest.fixture
def warudo_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    yield sock
    sock.close()


@pytest.fixture
def proxy(tmp_path, warudo_socket):
    config = Config(
        listen_port=0,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    p = FaceProxy(config, tmp_path)
    p.start()
    assert p.bind_error is None
    yield p
    p.stop()


def send_to_proxy(proxy, text=PACKET):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(text.encode("ascii"), ("127.0.0.1", proxy.bound_port))
    sock.close()


def recv_text(warudo_socket):
    data, _ = warudo_socket.recvfrom(65535)
    return data.decode("ascii")


def test_passthrough_forwards_verbatim(proxy, warudo_socket):
    send_to_proxy(proxy)
    assert recv_text(warudo_socket) == PACKET
    assert proxy.mode is Mode.PASSTHROUGH


def test_receive_stats_updates(proxy, warudo_socket):
    hz, since = proxy.receive_stats()
    assert hz == 0 and since is None
    send_to_proxy(proxy)
    recv_text(warudo_socket)
    hz, since = proxy.receive_stats()
    assert hz >= 1
    assert since is not None and since < 1.0


def test_recording_saves_and_keeps_forwarding(proxy, warudo_socket, tmp_path):
    proxy.start_recording()
    assert proxy.mode is Mode.RECORDING
    for i in range(3):
        send_to_proxy(proxy, f"a-{i}|trackingStatus-1|=|head#0,0,0|")
        assert recv_text(warudo_socket) == f"a-{i}|trackingStatus-1|=|head#0,0,0|"
    time.sleep(0.1)  # 수신 스레드의 feed 완료 대기
    clip_path = proxy.stop_recording("mytest")
    assert proxy.mode is Mode.PASSTHROUGH
    assert clip_path == tmp_path / "clips" / "mytest.jsonl"
    lines = clip_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_bind_error_reported(tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    port = blocker.getsockname()[1]
    p = FaceProxy(Config(listen_port=port), tmp_path)
    p.start()
    assert p.bind_error is not None
    assert str(port) in p.bind_error
    blocker.close()
    p.stop()  # 이미 닫힌 소켓에 대해 stop()이 예외 없이 동작하는지 검증


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def make_clip(proxy, entries):
    proxy.clips_dir.mkdir(parents=True, exist_ok=True)
    path = proxy.clips_dir / "test.jsonl"
    path.write_text(
        "\n".join(jsonlib.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return path


def test_playback_blocks_live_and_sends_clip(proxy, warudo_socket):
    # 이 테스트에서는 사전 라이브 수신이 없으므로 리드인 크로스페이드도 없다
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-10|trackingStatus-1|=|head#0,0,0|"},
        {"t": 50, "d": "a-20|trackingStatus-1|=|head#0,0,0|"},
    ])
    count = proxy.start_playback(clip, loop=False)
    assert count == 2
    assert proxy.mode is Mode.PLAYING
    send_to_proxy(proxy, "live-99|trackingStatus-1|=|head#0,0,0|")  # 차단돼야 함
    received = [recv_text(warudo_socket), recv_text(warudo_socket)]
    values = [parse_packet(p).blendshapes["a"] for p in received]
    assert values == [10, 20]
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
    # 차단된 라이브 패킷(live-99)이 뒤늦게라도 전달되지 않았음을 확인
    warudo_socket.settimeout(0.3)
    with pytest.raises(socket.timeout):
        warudo_socket.recvfrom(65535)


def test_playback_loop_and_stop(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 30, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=True)
    for _ in range(5):  # 루프이므로 클립 길이 이상 수신됨
        recv_text(warudo_socket)
    proxy.stop_playback()
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_apply_config_forward_change(proxy, warudo_socket):
    new_warudo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    new_warudo.bind(("127.0.0.1", 0))
    new_warudo.settimeout(2.0)
    try:
        new = Config(
            listen_port=proxy.bound_port,  # 현재 바인드 포트 그대로 -> 재시작 없음
            forward_port=new_warudo.getsockname()[1],
            crossfade_live_ms=2000,
        )
        assert proxy.apply_config(new) is None
        send_to_proxy(proxy)
        data, _ = new_warudo.recvfrom(65535)
        assert data.decode("ascii") == PACKET
    finally:
        new_warudo.close()


def test_apply_config_crossfade_applies_to_next_playback(proxy, warudo_socket):
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=700,
        crossfade_loop_ms=900,
    )
    assert proxy.apply_config(new) is None
    clip = make_clip(proxy, [{"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"}])
    assert proxy.start_playback(clip, loop=False) == 1
    player = proxy._player
    assert player._crossfade_live_ms == 700
    assert player._crossfade_loop_ms == 900
    recv_text(warudo_socket)
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_apply_config_listen_port_restart(proxy, warudo_socket):
    old_bound = proxy.bound_port
    new = Config(
        listen_port=0,  # 0 != bound_port -> 재시작 (새 OS 할당 포트)
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    assert proxy.apply_config(new) is None
    assert proxy.bind_error is None
    assert proxy.bound_port is not None
    send_to_proxy(proxy)  # send_to_proxy는 갱신된 bound_port를 사용
    assert recv_text(warudo_socket) == PACKET
    assert old_bound is not None  # (참고용 -- 값 비교는 OS 재할당 가능성 때문에 안 함)


def test_apply_config_rejected_while_recording(proxy, warudo_socket):
    proxy.start_recording()
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    error = proxy.apply_config(new)
    assert error is not None and "패스스루" in error
    proxy.stop_recording("cleanup")


def test_apply_config_rejected_while_playing(proxy, warudo_socket):
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-1|trackingStatus-1|=|head#0,0,0|"},
        {"t": 30, "d": "a-2|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=True)  # 루프로 재생 상태 유지
    new = Config(
        listen_port=proxy.bound_port,
        forward_port=warudo_socket.getsockname()[1],
        crossfade_live_ms=2000,
    )
    error = proxy.apply_config(new)
    assert error is not None and "패스스루" in error
    proxy.stop_playback()
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)


def test_apply_config_rollback_on_bind_failure(proxy, warudo_socket):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 0))
    try:
        new = Config(
            listen_port=blocker.getsockname()[1],  # 사용 중인 포트
            forward_port=warudo_socket.getsockname()[1],
            crossfade_live_ms=2000,
        )
        error = proxy.apply_config(new)
        assert error is not None and "이전 포트 유지" in error
        assert proxy.bind_error is None  # 롤백 성공으로 복원됨
        send_to_proxy(proxy)  # 이전 포트로 계속 수신
        assert recv_text(warudo_socket) == PACKET
    finally:
        blocker.close()


def test_fade_back_to_live(proxy, warudo_socket):
    # 라이브를 먼저 살려둔다 (0.5초 내 수신 이력 -> 리드인/복귀 페이드 모두 발동)
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    recv_text(warudo_socket)
    clip = make_clip(proxy, [
        {"t": 0, "d": "a-0|trackingStatus-1|=|head#0,0,0|"},
        {"t": 100, "d": "a-0|trackingStatus-1|=|head#0,0,0|"},
    ])
    proxy.start_playback(clip, loop=False)
    # 리드인 (fade 2000ms): t=0ms -> blend(100, 0, 0.0) = 100
    first = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert first == 100
    # t=100ms -> blend(100, 0, 0.05) = 95
    second = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert second == 95
    assert wait_until(lambda: proxy.mode is Mode.PASSTHROUGH)
    # 복귀 직후 라이브 패킷은 마지막 재생 프레임(a=95)과 블렌드되어 100 미만
    send_to_proxy(proxy, "a-100|trackingStatus-1|=|head#0,0,0|")
    value = parse_packet(recv_text(warudo_socket)).blendshapes["a"]
    assert 95 <= value < 100  # crossfade_live_ms=2000 창 안
