from __future__ import annotations

import logging
import os


def configure_logging(level: str | None = None) -> None:
    effective_level = (level or os.getenv("SICKLE_LOG_LEVEL") or "INFO").upper()
    numeric_level = getattr(logging, effective_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(module: str) -> logging.Logger:
    return logging.getLogger(f"sickle.{module}")
