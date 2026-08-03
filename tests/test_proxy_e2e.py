# tests/test_proxy_e2e.py
# 가짜 아이폰(UDP 송신) -> FaceProxy -> 가짜 Warudo(UDP 수신) 전체 시나리오
import json
import socket
import time

import pytest

from arkit_recorder.config import Config
from arkit_recorder.protocol import parse_packet
from arkit_recorder.proxy import FaceProxy, Mode


def make_packet(i):
    return f"jawOpen-{i}|eyeBlink_L-{i * 2}|trackingStatus-1|=|head#{i}.0,0,0|"


def test_full_scenario(tmp_path):
    warudo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    warudo.bind(("127.0.0.1", 0))
    warudo.settimeout(2.0)
    phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    config = Config(listen_port=0, forward_port=warudo.getsockname()[1])
    proxy = FaceProxy(config, tmp_path)
    proxy.start()
    assert proxy.bind_error is None
    addr = ("127.0.0.1", proxy.bound_port)

    try:
        # 1) 패스스루: 폰 패킷이 그대로 Warudo에 도착
        phone.sendto(make_packet(1).encode("ascii"), addr)
        data, _ = warudo.recvfrom(65535)
        assert data.decode("ascii") == make_packet(1)

        # 2) 녹화: 5 프레임 기록, 패스스루 유지
        proxy.start_recording()
        for i in range(5):
            phone.sendto(make_packet(i).encode("ascii"), addr)
            warudo.recvfrom(65535)  # 전달 확인
            time.sleep(0.02)
        time.sleep(0.1)
        clip_path = proxy.stop_recording("e2e")
        lines = clip_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        entries = [json.loads(x) for x in lines]
        # 첫 프레임은 start_recording 시점 기준 수 ms 뒤에 도착한다
        assert 0 <= entries[0]["t"] < 500
        assert all(entries[i]["t"] <= entries[i + 1]["t"] for i in range(4))

        # 3) 재생: 라이브 차단 + 클립 프레임 수신
        # 마지막 폰 패킷에서 0.5초 넘게 기다려 리드인 크로스페이드가
        # 걸리지 않게 한다 (원본 값 그대로 수신되어야 검증이 단순해짐)
        time.sleep(0.6)
        count = proxy.start_playback(clip_path, loop=False)
        assert count == 5
        received = []
        for _ in range(5):
            data, _ = warudo.recvfrom(65535)
            received.append(data.decode("ascii"))
        values = [parse_packet(p).blendshapes["jawOpen"] for p in received]
        assert values == [0, 1, 2, 3, 4]

        # 4) 재생 종료 후 패스스루 복귀
        deadline = time.time() + 3.0
        while proxy.mode is not Mode.PASSTHROUGH and time.time() < deadline:
            time.sleep(0.02)
        assert proxy.mode is Mode.PASSTHROUGH
    finally:
        proxy.stop()
        phone.close()
        warudo.close()
