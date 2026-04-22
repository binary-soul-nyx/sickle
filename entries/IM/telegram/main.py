from __future__ import annotations

from sickle.config import load_config
from sickle.host import Sickle
from sickle.logs import configure_logging, get_logger

from .app import build_application


def main() -> None:
    config = load_config()
    configure_logging(config.log_level)
    logger = get_logger("entries.telegram")

    sickle = Sickle(config=config)
    application = build_application(config=config, sickle=sickle)

    logger.info("Telegram polling started")
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
