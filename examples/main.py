from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def run() -> int:
    from prometheus_telegram_bot.entrypoint.main import main

    examples_dir = Path(__file__).resolve().parent
    default_config = examples_dir / "bot-config.yaml"

    argv = sys.argv[1:]
    if not argv:
        argv = ["--config", str(default_config)]

    return main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
