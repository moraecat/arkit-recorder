# main.py
import sys
from pathlib import Path

from arkit_recorder.config import load_config
from arkit_recorder.proxy import FaceProxy
from arkit_recorder.qt.app import run_app

if getattr(sys, "frozen", False):
    # PyInstaller 빌드: __file__은 임시 해제 폴더를 가리키므로 exe 위치 기준
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    config_path = BASE_DIR / "config.json"
    config = load_config(config_path)
    proxy = FaceProxy(config, BASE_DIR)
    proxy.start()
    try:
        raise SystemExit(run_app(proxy, config, config_path))
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
