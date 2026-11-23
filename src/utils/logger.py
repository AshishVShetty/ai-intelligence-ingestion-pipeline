"""Standardized logging configuration for the ingestion pipeline."""

import logging
import sys


def get_logger(name: str = "arxiv_crawler") -> logging.Logger:
    """Return a configured logger instance with formatted console output."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger
