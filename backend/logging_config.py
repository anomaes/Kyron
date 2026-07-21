from __future__ import annotations

import logging

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_application_logging(level_name: str) -> None:
    """Apply Kyron's log level without replacing Uvicorn's configured handlers."""
    level = logging.getLevelNamesMapping()[level_name.upper()]
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)
