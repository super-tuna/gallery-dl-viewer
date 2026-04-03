"""
Shared logging configuration for gallery-dl-viewer modules.

Log level is controlled by the LOG_LEVEL environment variable (default: INFO).
Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL

Example:
    LOG_LEVEL=DEBUG python indexer.py
    LOG_LEVEL=DEBUG uvicorn app:app ...
"""

import logging
import os
import sys


def configure(verbose: bool = False) -> None:
    """Configure root logger.

    If *verbose* is True (e.g. --verbose CLI flag), level is forced to DEBUG
    regardless of LOG_LEVEL.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if verbose:
        level = logging.DEBUG

    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
