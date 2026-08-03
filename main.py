# main.py
from pathlib import Path

from arkit_recorder.config import load_config
from arkit_recorder.gui import run_gui
from arkit_recorder.proxy import FaceProxy

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
