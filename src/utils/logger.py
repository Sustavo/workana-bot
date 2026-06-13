import sys

from loguru import logger

from src.utils.config import Settings

# Guardamos o id do sink de stderr pra poder suprimi-lo enquanto o rich.Live
# está ativo (senão as linhas de log corrompem o dashboard). O sink de ARQUIVO
# (run.log, DEBUG) fica SEMPRE ligado — nada se perde.
_STDERR_SINK_ID: int | None = None


def setup_logger(settings: Settings) -> None:
    global _STDERR_SINK_ID
    logger.remove()
    _STDERR_SINK_ID = logger.add(sys.stderr, level=settings.log_level, colorize=True)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.log_file,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )


def suppress_stderr_logging() -> None:
    """Remove o sink de stderr (chamar antes de abrir um rich.Live)."""
    global _STDERR_SINK_ID
    if _STDERR_SINK_ID is not None:
        try:
            logger.remove(_STDERR_SINK_ID)
        except ValueError:
            pass
        _STDERR_SINK_ID = None


def restore_stderr_logging(settings: Settings) -> None:
    """Recoloca o sink de stderr (chamar ao fechar o rich.Live)."""
    global _STDERR_SINK_ID
    if _STDERR_SINK_ID is None:
        _STDERR_SINK_ID = logger.add(sys.stderr, level=settings.log_level, colorize=True)
