# main.py
import sys
from pathlib import Path

from arkit_recorder.config import load_config
from arkit_recorder.gui import run_gui
from arkit_recorder.proxy import FaceProxy

if getattr(sys, "frozen", False):
    # PyInstaller 빌드: __file__은 임시 해제 폴더를 가리키므로 exe 위치 기준
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    config = load_config(BASE_DIR / "config.json")
    proxy = FaceProxy(config, BASE_DIR)
    proxy.start()
    try:
        run_gui(proxy, config)
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
