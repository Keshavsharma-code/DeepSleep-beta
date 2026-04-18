"""Pytest configuration — silence structlog output during tests."""
import logging
import structlog


def pytest_configure(config):
    del config  # unused — required by pytest hook signature
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(),
    )
