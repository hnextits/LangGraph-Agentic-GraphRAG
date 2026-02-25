"""Central logging configuration for the backend services."""
from __future__ import annotations

import logging

LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(level: int = LOG_LEVEL, fmt: str = LOG_FORMAT) -> None:
    """Configure the root logger with a consistent formatter."""
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(level=level, format=fmt)
        return

    root_logger.setLevel(level)
    formatter = logging.Formatter(fmt)
    for handler in root_logger.handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)


__all__ = ["configure_logging", "LOG_LEVEL", "LOG_FORMAT"]
