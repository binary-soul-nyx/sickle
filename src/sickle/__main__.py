from __future__ import annotations

from .config import load_config
from .errors import ConfigError
from .logs import configure_logging, get_logger


def main() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Sickle failed to load config: {exc}")
        return

    configure_logging(config.log_level)
    logger = get_logger("__main__")
    allowed_count = len(config.telegram.allowed_user_ids)

    logger.info("Sickle bootstrap complete")
    print(f"Sickle ready. allowed_user_ids={allowed_count}")


if __name__ == "__main__":
    main()
