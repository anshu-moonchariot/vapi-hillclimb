"""Structured logging setup with run_id context."""

import logging
import sys


def get_logger(name: str, run_id: str = "") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = "%(asctime)s [%(levelname)s] %(name)s"
        if run_id:
            fmt += f" [{run_id}]"
        fmt += " — %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
