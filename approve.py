"""Review interativo dos drafts. Aprova → abre browser e envia."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

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


REPORTS_DIR = Path(__file__).parent / "data" / "reports"


def _classify_error(err: str) -> str:
    low = err.lower()
    if "enviar orçamento" in low or ("timeout" in low and "submit" in low):
        return "Botão 'Enviar orçamento' não apareceu/clicável — form pode ter mudado ou valor abaixo do mínimo aceito."
    if "min" in low and "amount" in low:
        return "Valor abaixo do mínimo exigido pelo Workana."
    if "ensure_logged_in" in low or "anônima" in low or "login" in low:
        return "Sessão deslogada — refaça o login no browser."
    if "wait_for_selector" in low or "wait_for_url" in low or "timeout" in low:
        return "Elemento esperado não apareceu no tempo limite — seletor pode ter mudado ou página lenta."
    if "bidform" in low:
        return "Form #bidForm não carregou — vaga pode ter sido fechada ou já foi enviada uma proposta."
    return "Erro não classificado — confira o stacktrace no log."


def _write_failure_report(failed: list[tuple[str, dict, str]], total_approved: int) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"falhas-{ts}.md"

    lines: list[str] = []
    lines.append(f"# Falhas no envio — {ts}\n")
    lines.append(f"**{len(failed)} falha(s) de {total_approved} aprovado(s).**\n")
    for slug, payload, err in failed:
        prop = payload.get("proposal", {})
        job = payload.get("job", {})
        lines.append(f"\n---\n\n## {slug}\n")
        lines.append(f"- **URL da vaga:** {job.get('url', '?')}")
        lines.append(f"- **URL do bid:** https://www.workana.com/messages/bid/{slug}")
        lines.append(f"- **Título:** {job.get('title', '?')}")
        lines.append(f"- **Valor proposto:** R$ {prop.get('amount_brl', 0):.2f}")
        lines.append(f"- **Prazo:** {prop.get('delivery_time', '?')}")
        hours = prop.get("hours_estimate")
        lines.append(f"- **Horas:** {hours if hours is not None else '—'}")
        lines.append(f"- **Possível causa:** {_classify_error(err)}\n")
        lines.append("**Erro:**\n")
        lines.append(f"```\n{err}\n```\n")
        lines.append("**Texto da proposta:**\n")
        for ln in (prop.get("content") or "(vazio)").splitlines():
            lines.append(f"> {ln}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _print_draft(console: Console, slug: str, payload: dict, idx: int, total: int) -> None:
    job = payload["job"]
    prop = payload["proposal"]
    insight = payload.get("insight") or {}

    meta = Table.grid(padding=(0, 1))
    meta.add_row("[bold]Vaga[/]", job.get("title", ""))
    meta.add_row("[bold]URL[/]", job.get("url", ""))
    meta.add_row("[bold]Orçamento cliente[/]", job.get("budget_text", ""))
    meta.add_row("[bold]Skills[/]", ", ".join(job.get("skills") or []))
    meta.add_row("[bold]Média concorrentes[/]", str(insight.get("avg_bid_text") or "?"))
    meta.add_row("[bold]Status[/]", job.get("proposals_status", ""))
    console.print(Panel(meta, title=f"[cyan][{idx}/{total}] {slug}", border_style="cyan"))

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
    fallback_skill = (profile.get("skills") or ["Programação"])[0]
    max_hourly_rate = float(profile.get("max_hourly_rate_brl", 150))

    drafts = tracker.list_pending_drafts()
    if not drafts:
        print("Nenhum draft pendente. Rode `python -m src.main scrape` primeiro.")
        tracker.close()
        return 0

    console = Console()
    total = len(drafts)
    console.print(f"[bold cyan]{total}[/] drafts pendentes pra validar\n")
    approved: list[tuple[str, dict]] = []
    rejected_n = 0
    skipped_n = 0
    for i, d in enumerate(drafts, start=1):
        _print_draft(console, d["slug"], d["payload"], i, total)
        ans = Prompt.ask(
            "[bold]Aprovar e enviar?[/] [y]es / [n]o / [s]kip / [e]ditar e enviar",
            choices=["y", "n", "s", "e"],
            default="n",
        )
        if ans == "y":
            approved.append((d["slug"], d["payload"]))
            label = "[green]aprovado[/]"
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
            label = "[green]editado e aprovado[/]"
        elif ans == "n":
            tracker.mark_draft(d["slug"], "rejected")
            rejected_n += 1
            label = "[red]rejeitado[/]"
        else:
            skipped_n += 1
            label = "[yellow]pulado[/]"
        console.print(f"  → {label} | faltam [bold]{total - i}[/] pra validar\n")

    console.print(
        f"\nResumo da revisão: [green]{len(approved)} aprovados[/], "
        f"[red]{rejected_n} rejeitados[/], [yellow]{skipped_n} pulados[/]"
    )

    if not approved:
        print("Nada aprovado pra enviar. Saindo.")
        tracker.close()
        return 0

    sent_n = 0
    failed: list[tuple[str, dict, str]] = []
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
                if bid_form.is_hourly_form(page):
                    if amount > max_hourly_rate:
                        logger.warning(
                            "[{}] Form é por hora — capando R$ {:.2f} → R$ {:.2f}/h",
                            slug, amount, max_hourly_rate,
                        )
                        amount = max(max_hourly_rate, min_amt)
                bid_form.fill_form(
                    page,
                    bid_form.BidPayload(
                        amount=amount,
                        delivery_time=prop["delivery_time"],
                        hours=prop.get("hours_estimate"),
                        content=prop["content"],
                        featured_portfolio_ids=portfolio_ids,
                    ),
                    fill_delivery_time=settings.fill_delivery_time,
                )
                bid_form.ensure_skill_selected(page, fallback_skill)
                bid_form.select_portfolio(page, portfolio_ids)
                bid_form.submit(page)
                tracker.mark_draft(slug, "sent")
                tracker.record_submission(slug, amount, prop["delivery_time"], prop["content"])
                job_url = payload.get("job", {}).get("url") or payload.get("card", {}).get("url") or ""
                tracker.upsert_job(slug, payload.get("job", {}).get("title", ""), job_url, "sent")
                logger.success("Enviado: {}", slug)
                sent_n += 1
                human_sleep(settings)
            except Exception as e:
                logger.exception("Falha enviando {}: {}", slug, e)
                failed.append((slug, payload, str(e)))

    console.print(
        f"\n[bold]Envio concluído:[/] [green]{sent_n}[/] enviado(s) com sucesso, "
        f"[red]{len(failed)}[/] falhou/falharam (de {len(approved)} aprovado(s))."
    )
    if failed:
        report = _write_failure_report(failed, len(approved))
        console.print(f"  → Relatório de falhas: [yellow]{report}[/]")

    tracker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
