import socket
import time
from pathlib import Path

import pytest

from arkit_recorder.config import Config
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
