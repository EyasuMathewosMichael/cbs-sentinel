"""Minimal Phase 0 application entry point."""

import logging

from sentinel.config import Settings
from sentinel.logging_config import configure_logging


def create_application() -> Settings:
    """Load configuration and initialize logging for the application process."""
    settings = Settings.from_environment()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("SENTINEL foundation initialized")
    return settings


def run() -> None:
    """Start the Phase 0 application entry point."""
    create_application()


if __name__ == "__main__":
    run()
