import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config import Config


def setup_logger(
    name: str,
    log_file: Optional[Path] = None,
    level: str = "INFO"
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.propagate = False  # don't bubble to root handler installed by bitcoinlib/ipv8 basicConfig()

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=Config.LOG_MAX_BYTES,
            backupCount=1,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
