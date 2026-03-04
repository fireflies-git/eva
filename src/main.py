"""Application entrypoint."""

from eva.app import EvaApp
from eva.config import load_settings
from eva.logging import configure_logging


def main() -> None:
    configure_logging()
    settings = load_settings()
    app = EvaApp(settings=settings)
    app.run()


if __name__ == "__main__":
    main()
