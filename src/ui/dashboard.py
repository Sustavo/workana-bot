"""Dashboard ao vivo (rich.Live) pros loops de scrape e de envio.

Mostra contadores (total/processados/gerados/enviados/falhas/pulados), a vaga
atual, média de concorrentes vs valor escolhido, conexões restantes e ritmo/min.
Coexiste com loguru suprimindo o sink de stderr enquanto o Live está ativo
(o arquivo run.log continua em DEBUG). Pausas de input() devem ocorrer FORA
do `with Dashboard(...)`.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from src.utils.config import Settings
from src.utils.logger import restore_stderr_logging, suppress_stderr_logging


def _money(v: float | None) -> str:
    return f"R$ {v:,.2f}" if v is not None else "—"


@dataclass
class DashState:
    phase: str                       # "scrape" | "submit"
    speed_profile: str = ""
    total: int = 0
    processed: int = 0
    generated: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    current_slug: str = ""
    current_title: str = ""
    competitor_avg: float | None = None
    chosen_amount: float | None = None
    min_amount: float | None = None
    connections_left: int | None = None
    last_event: str = ""
    started_at: float = field(default_factory=time.monotonic)

    def rate_per_min(self) -> float:
        el = time.monotonic() - self.started_at
        return (self.processed / el * 60) if el > 0 else 0.0

    def elapsed_str(self) -> str:
        el = int(time.monotonic() - self.started_at)
        return f"{el // 60}m{el % 60:02d}s"


def _render(state: DashState) -> Group:
    title = "Scraping + geração de drafts" if state.phase == "scrape" else "Enviando propostas"
    target_lbl = "Alvo" if state.phase == "scrape" else "Total"

    counts = Table.grid(padding=(0, 2))
    counts.add_column(justify="right")
    counts.add_column()
    counts.add_column(justify="right")
    counts.add_column()
    counts.add_row(f"{target_lbl}:", str(state.total), "Processados:", str(state.processed))
    counts.add_row("Gerados:", str(state.generated), "Enviados:", f"[green]{state.sent}[/]")
    counts.add_row("Falhas:", f"[red]{state.failed}[/]", "Pulados:", f"[yellow]{state.skipped}[/]")
    conn = str(state.connections_left) if state.connections_left is not None else "—"
    counts.add_row("Conexões restantes:", conn, "Ritmo/min:", f"{state.rate_per_min():.1f}")

    cur = Table.grid(padding=(0, 1))
    cur.add_column(justify="right", style="bold")
    cur.add_column()
    cur.add_row("Atual:", f"{state.current_slug}")
    cur.add_row("Título:", (state.current_title or "")[:60])
    cur.add_row("Média concorrentes:", _money(state.competitor_avg))
    chosen = _money(state.chosen_amount)
    if state.min_amount:
        chosen += f"  (mín. {_money(state.min_amount)})"
    cur.add_row("Valor escolhido:", chosen)
    cur.add_row("Último evento:", state.last_event or "—")

    header = f"[cyan]{title}[/]"
    if state.speed_profile:
        header += f"  ·  [dim]velocidade: {state.speed_profile} · {state.elapsed_str()}[/]"

    return Group(
        Panel(counts, title=header, border_style="cyan"),
        Panel(cur, title="[magenta]Vaga atual", border_style="magenta"),
    )


class Dashboard:
    """Context manager. Quando `enabled=False`, vira no-op e mantém o log normal."""

    def __init__(self, state: DashState, settings: Settings, enabled: bool = True,
                 console: Console | None = None) -> None:
        self.state = state
        self.settings = settings
        self.enabled = enabled
        self._console = console or Console()
        self._live: Live | None = None

    def __enter__(self) -> "Dashboard":
        if self.enabled:
            suppress_stderr_logging()
            self._live = Live(
                _render(self.state), console=self._console,
                refresh_per_second=4, transient=False,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            self._live.__exit__(*exc)
            self._live = None
        if self.enabled:
            restore_stderr_logging(self.settings)

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(_render(self.state))

    @contextmanager
    def paused(self):
        """Pausa o Live e religa o log de stderr pra rodar input()/prompts sem
        corromper a tela. Ao sair, volta a suprimir o stderr e religa o Live."""
        if self._live is not None:
            self._live.stop()
        if self.enabled:
            restore_stderr_logging(self.settings)
        try:
            yield
        finally:
            if self.enabled:
                suppress_stderr_logging()
            if self._live is not None:
                self._live.start(refresh=True)

    def update(self, event: str | None = None, **kw) -> None:
        for k, val in kw.items():
            setattr(self.state, k, val)
        if event is not None:
            self.state.last_event = event
        self._refresh()

    # ── conveniências ─────────────────────────────────────
    def start_job(self, slug: str, title: str = "") -> None:
        self.state.current_slug = slug
        self.state.current_title = title
        self.state.competitor_avg = None
        self.state.chosen_amount = None
        self.state.min_amount = None
        self.state.processed += 1
        self.update(event=f"processando {slug}")

    def mark_generated(self, slug: str, amount: float, avg: float | None = None) -> None:
        self.state.generated += 1
        self.state.chosen_amount = amount
        if avg is not None:
            self.state.competitor_avg = avg
        self.update(event=f"draft gerado {slug} ({_money(amount)})")

    def mark_sent(self, slug: str, amount: float, min_amount: float | None = None) -> None:
        self.state.sent += 1
        self.state.chosen_amount = amount
        self.state.min_amount = min_amount
        self.update(event=f"enviado {slug} ({_money(amount)})")

    def mark_failed(self, slug: str, reason: str) -> None:
        self.state.failed += 1
        self.update(event=f"[red]falha {slug}: {reason[:60]}[/]")

    def mark_skipped(self, slug: str, reason: str = "") -> None:
        self.state.skipped += 1
        self.update(event=f"[yellow]pulado {slug}{(': ' + reason[:50]) if reason else ''}[/]")
