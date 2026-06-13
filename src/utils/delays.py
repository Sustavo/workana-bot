"""Delays "humanos" entre ações pra reduzir risco de ban.

Anti-bot moderno detecta PADRÃO de timing (intervalos fixos). Por isso:
- intervalo base aleatório na faixa do perfil de velocidade;
- pausa longa ocasional (probabilística) simulando o humano que "se distrai";
- teto opcional de ações por hora (janela deslizante) pra não estourar limites.
"""
import random
import time
from collections import deque

from src.utils.config import Settings

# Janela deslizante (timestamps monotônicos) das últimas ações, p/ o teto/hora.
# Module-level: ok porque os loops aqui são sequenciais e single-process.
_action_times: deque[float] = deque()


def _enforce_hourly_cap(settings: Settings) -> None:
    cap = getattr(settings, "max_actions_per_hour", 0) or 0
    if cap <= 0:
        return
    now = time.monotonic()
    while _action_times and now - _action_times[0] > 3600:
        _action_times.popleft()
    if len(_action_times) >= cap:
        wait = 3600 - (now - _action_times[0]) + 1
        if wait > 0:
            time.sleep(wait)
        # limpa de novo após esperar
        now = time.monotonic()
        while _action_times and now - _action_times[0] > 3600:
            _action_times.popleft()
    _action_times.append(time.monotonic())


def human_sleep(settings: Settings, label: str = "") -> None:
    _enforce_hourly_cap(settings)
    seconds = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
    chance = getattr(settings, "long_pause_chance", 0.0) or 0.0
    if chance > 0 and random.random() < chance:
        lo = getattr(settings, "long_pause_min_seconds", 0.0) or 0.0
        hi = getattr(settings, "long_pause_max_seconds", 0.0) or 0.0
        if hi > 0:
            seconds += random.uniform(lo, hi)
    time.sleep(seconds)


def short_jitter(max_seconds: float = 1.0) -> None:
    time.sleep(random.uniform(0.2, max_seconds))


def reset_action_window() -> None:
    """Zera a janela do teto/hora (útil em testes ou entre fases)."""
    _action_times.clear()
