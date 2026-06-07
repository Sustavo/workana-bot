import random
import time

from src.utils.config import Settings


def human_sleep(settings: Settings, label: str = "") -> None:
    seconds = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
    time.sleep(seconds)


def short_jitter(max_seconds: float = 1.0) -> None:
    time.sleep(random.uniform(0.2, max_seconds))
