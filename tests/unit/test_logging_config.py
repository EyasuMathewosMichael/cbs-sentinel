import logging

from sentinel.logging_config import configure_logging


def test_configure_logging_accepts_case_insensitive_level():
    configure_logging("debug")

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_falls_back_for_unknown_level():
    configure_logging("not-a-level")

    assert logging.getLogger().level == logging.INFO
