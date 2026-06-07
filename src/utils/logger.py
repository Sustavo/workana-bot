import sys

from loguru import logger

from src.utils.config import Settings


def setup_logger(settings: Settings) -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, colorize=True)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.log_file,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )
