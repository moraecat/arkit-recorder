import json

from arkit_recorder.config import Config, load_config, save_config


def test_creates_default_file(tmp_path):
    path = tmp_path / "config.json"
    config = load_config(path)
    assert config == Config()
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["listen_port"] == 49983
    assert saved["forward_port"] == 49984
    assert saved["crossfade_live_ms"] == 300
    assert saved["crossfade_loop_ms"] == 500


def test_loads_existing_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"listen_port": 15000, "unknown_key": 1}), encoding="utf-8")
    config = load_config(path)
    assert config.listen_port == 15000
    assert config.forward_port == 49984  # 명시 안 된 항목은 기본값


def test_save_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    config = Config(listen_port=15000, crossfade_live_ms=700)
    save_config(path, config)
    assert load_config(path) == config
