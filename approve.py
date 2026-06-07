"""Review interativo dos drafts. Aprova → abre browser e envia."""
from __future__ import annotations

import sys

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.browser.session import ensure_logged_in, open_context
from src.db.tracker import Tracker
from src.scraper import bid_form
from src.utils.config import Settings, load_profile
from src.utils.delays import human_sleep
from src.utils.logger import setup_logger


def _print_draft(console: Console, slug: str, payload: dict) -> None:
    job = payload["job"]
    prop = payload["proposal"]
    insight = payload.get("insight") or {}

    meta = Table.grid(padding=(0, 1))
    meta.add_row("[bold]Vaga[/]", job.get("title", ""))
    meta.add_row("[bold]URL[/]", job.get("url", ""))
    meta.add_row("[bold]Orçamento cliente[/]", job.get("budget_text", ""))
    meta.add_row("[bold]Skills[/]", ", ".join(job.get("skills") or []))
    meta.add_row("[bold]Média concorrentes[/]", str(insight.get("avg_bid_text") or "?"))
    meta.add_row("[bold]Nº concorrentes[/]", str(insight.get("competitor_count") or "?"))
    meta.add_row("[bold]Status[/]", job.get("proposals_status", ""))
    console.print(Panel(meta, title=f"[cyan]{slug}", border_style="cyan"))

    bid = Table.grid(padding=(0, 1))
    bid.add_row("[bold]Valor[/]", f"R$ {prop['amount_brl']:.2f}")
    bid.add_row("[bold]Prazo[/]", prop["delivery_time"])
    bid.add_row("[bold]Horas[/]", str(prop.get("hours_estimate") or "—"))
    console.print(Panel(bid, title="[green]Proposta de bid", border_style="green"))

    console.print(Panel(prop["content"], title="[yellow]Texto", border_style="yellow"))


def main() -> int:
    settings = Settings.load()
    setup_logger(settings)
    tracker = Tracker(settings.database_path)
    profile = load_profile()
    portfolio_ids = [str(x) for x in (profile.get("featured_portfolio_ids") or [])]

    drafts = tracker.list_pending_drafts()
    if not drafts:
        print("Nenhum draft pendente. Rode `python -m src.main scrape` primeiro.")
        tracker.close()
        return 0

    console = Console()
    approved: list[tuple[str, dict]] = []
    for d in drafts:
        _print_draft(console, d["slug"], d["payload"])
        ans = Prompt.ask(
            "[bold]Aprovar e enviar?[/] [y]es / [n]o / [s]kip / [e]ditar e enviar",
            choices=["y", "n", "s", "e"],
            default="n",
        )
        if ans == "y":
            approved.append((d["slug"], d["payload"]))
        elif ans == "e":
            console.print("Cole o novo texto. Termine com uma linha contendo apenas '.':")
            lines: list[str] = []
            while True:
                line = input()
                if line.strip() == ".":
                    break
                lines.append(line)
            d["payload"]["proposal"]["content"] = "\n".join(lines)
            new_amount = Prompt.ask("Novo valor (R$)", default=str(d["payload"]["proposal"]["amount_brl"]))
            d["payload"]["proposal"]["amount_brl"] = float(new_amount)
            new_prazo = Prompt.ask("Novo prazo", default=d["payload"]["proposal"]["delivery_time"])
            d["payload"]["proposal"]["delivery_time"] = new_prazo
            approved.append((d["slug"], d["payload"]))
        elif ans == "n":
            tracker.mark_draft(d["slug"], "rejected")
        else:
            pass

    if not approved:
        print("Nada aprovado pra enviar. Saindo.")
        tracker.close()
        return 0

    with open_context(settings) as ctx:
        ensure_logged_in(ctx, settings.workana_jobs_url)
        page = ctx.pages[0]
        for slug, payload in approved:
            prop = payload["proposal"]
            try:
                bid_form.open_bid_page(page, slug)
                human_sleep(settings)
                min_amt = bid_form.read_min_amount(page) or 0
                amount = max(prop["amount_brl"], min_amt)
                bid_form.fill_form(
                    page,
                    bid_form.BidPayload(
                        amount=amount,
                        delivery_time=prop["delivery_time"],
                        hours=prop.get("hours_estimate"),
                        content=prop["content"],
                        featured_portfolio_ids=portfolio_ids,
                    ),
                )
                bid_form.select_portfolio(page, portfolio_ids)
                Prompt.ask(f"[{slug}] Formulário preenchido. Confirme visualmente e ENTER pra enviar", default="ok")
                bid_form.submit(page)
                tracker.mark_draft(slug, "sent")
                tracker.record_submission(slug, amount, prop["delivery_time"], prop["content"])
                logger.success("Enviado: {}", slug)
                human_sleep(settings)
            except Exception as e:
                logger.exception("Falha enviando {}: {}", slug, e)
                Prompt.ask(f"[{slug}] Falhou. ENTER pra seguir pro próximo", default="ok")

    tracker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
