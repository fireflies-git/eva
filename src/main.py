"""Application entrypoint."""

import sys

from eva.app import EvaApp
from eva.cli import run_settings
from eva.config import load_settings
from eva.logging import configure_logging


def main() -> None:
    configure_logging()
    if len(sys.argv) > 1 and sys.argv[1] == "settings":
        raise SystemExit(run_settings(sys.argv[2:]))
    settings = load_settings()
    app = EvaApp(settings=settings)
    app.run()


if __name__ == "__main__":
    main()
