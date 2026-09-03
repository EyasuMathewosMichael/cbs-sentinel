"""Structured logging configuration for the application foundation."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure a consistent, timestamped application log format."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(numeric_level)
