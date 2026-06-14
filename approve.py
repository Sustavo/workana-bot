"""Review interativo dos drafts. Aprova → abre browser e envia."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.browser import guard, session
from src.db.tracker import Tracker
from src.scraper import bid_form
from src.ui.dashboard import Dashboard, DashState
from src.utils.config import Settings, load_profile
from src.utils.delays import human_sleep
from src.utils.errors import BidUnavailableError, StopRun, SuspiciousActivityError
from src.utils.logger import setup_logger


REPORTS_DIR = Path(__file__).parent / "data" / "reports"


def _classify_error(err: str) -> str:
    low = err.lower()
    if "não consegui fixar o valor" in low or "nao consegui fixar o valor" in low or "derivou" in low:
        return "O valor do campo foi reescrito pelo form (Vue) e não deu pra fixar — envio cancelado pra não mandar valor errado."
    if "acesso negado" in low:
        return "Vaga sem permissão de lance ('Acesso Negado') — pulada e descartada."
    if "abaixo do mínimo" in low or "abaixo do minimo" in low or ("min" in low and "amount" in low):
        return "Valor abaixo do mínimo exigido pelo Workana — o envio foi bloqueado (NÃO marcado como enviado)."
    if "sem redirect" in low or "não confirmado" in low or "nao confirmado" in low or "/bid/ após submit" in low:
        return "Envio NÃO confirmado (sem redirect/sucesso) — possível erro de validação ou página lenta."
    if "form rejeitou" in low:
        return "O Workana rejeitou o formulário (mensagem de validação visível)."
    if "nenhum botão" in low or "enviar orçamento" in low:
        return "Botão 'Enviar orçamento' não apareceu/clicável — form pode ter mudado."
    if "atividade suspeita" in low or "captcha" in low or "bloqueio" in low:
        return "Atividade suspeita/bloqueio do Workana — automação pausada/abortada pra evitar ban."
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


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="approve.py", description="Revisa e envia os drafts de propostas."
    )
    p.add_argument(
        "--speed", choices=["conservador", "equilibrado", "rapido"], default=None,
        help="Perfil de velocidade (sobrepõe SPEED_PROFILE do .env).",
    )
    p.add_argument(
        "--all", "-a", action="store_true", dest="all",
        help="Aprova e envia TODOS os pendentes de uma vez, sem revisar um a um.",
    )
    p.add_argument(
        "--yes", "-y", action="store_true", dest="yes",
        help="Com --all, envia sem pedir confirmação.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.load(speed_override=args.speed)
    setup_logger(settings)
    logger.info("Velocidade: {}", settings.speed_summary())
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
    approved: list[tuple[str, dict]] = []
    rejected_n = 0
    skipped_n = 0

    if args.all:
        # Botão "aprovar tudo": aprova todos os pendentes sem revisar (1 confirmação).
        approved = [(d["slug"], d["payload"]) for d in drafts]
        tbl = Table(title=f"[bold]{total}[/] propostas pendentes — modo --all (sem revisão)")
        tbl.add_column("#", justify="right", style="dim")
        tbl.add_column("Vaga")
        tbl.add_column("Valor", justify="right")
        tbl.add_column("Prazo")
        for i, d in enumerate(drafts, start=1):
            prop = d["payload"]["proposal"]
            tbl.add_row(str(i), d["slug"][:50], f"R$ {prop['amount_brl']:.2f}",
                        str(prop.get("delivery_time", "")))
        console.print(tbl)
        if not args.yes:
            ans = Prompt.ask(
                f"[bold red]Enviar TODAS as {total} propostas sem revisar?[/]",
                choices=["y", "n"], default="n",
            )
            if ans != "y":
                console.print("Cancelado. Nada enviado.")
                tracker.close()
                return 0
        console.print(f"[bold green]{total} aprovadas[/] automaticamente (modo --all).\n")
    else:
        console.print(f"[bold cyan]{total}[/] drafts pendentes pra validar\n")
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
    aborted: str | None = None

    # Abre o browser e loga ANTES do dashboard (ensure_logged_in pode pedir input).
    with session.open_context(settings) as ctx:
        session.ensure_logged_in(ctx, settings.workana_jobs_url)
        page = ctx.pages[0]

        state = DashState(phase="submit", speed_profile=settings.speed_profile, total=len(approved))
        with Dashboard(state, settings, enabled=not settings.headless) as dash:
            for slug, payload in approved:
                prop = payload["proposal"]
                job = payload.get("job", {})
                insight_avg = (payload.get("insight") or {}).get("avg_bid_value")

                if aborted:
                    failed.append((slug, payload, f"não enviado — run abortada: {aborted}"))
                    dash.mark_failed(slug, "abortada")
                    continue

                dash.start_job(slug, job.get("title", ""))
                if insight_avg is not None:
                    dash.update(competitor_avg=insight_avg)

                try:
                    bid_form.open_bid_page(page, slug)
                    if settings.guard_enabled:
                        guard.assert_safe(page, "bid_page")
                    human_sleep(settings)

                    # Valor: nunca abaixo do mínimo real do Workana (corrige o "valor errado").
                    amount, min_amt = bid_form.clamp_amount(page, prop["amount_brl"])
                    if bid_form.is_hourly_form(page):
                        if amount > max_hourly_rate:
                            logger.warning(
                                "[{}] Form é por hora — capando R$ {:.2f} → R$ {:.2f}/h",
                                slug, amount, max_hourly_rate,
                            )
                            amount = max(max_hourly_rate, min_amt)  # nunca abaixo do mínimo

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
                    # submit() re-afirma o valor (anti-clobber do Vue), trata o modal de
                    # confirmação e LEVANTA se o envio não for confirmado → só marca 'sent'
                    # no sucesso.
                    bid_form.submit(
                        page,
                        expected_amount=amount,
                        redirect_timeout_ms=settings.submit_redirect_timeout_ms,
                    )

                    tracker.mark_draft(slug, "sent")
                    tracker.record_submission(slug, amount, prop["delivery_time"], prop["content"])
                    job_url = job.get("url") or payload.get("card", {}).get("url") or ""
                    tracker.upsert_job(slug, job.get("title", ""), job_url, "sent")
                    logger.success("Enviado: {} (R$ {:.2f})", slug, amount)
                    sent_n += 1
                    dash.mark_sent(slug, amount, min_amt)
                    human_sleep(settings)

                except BidUnavailableError as e:
                    # "Acesso Negado" (vaga sem permissão de lance) → pula e DESCARTA o rascunho.
                    logger.info("[{}] acesso negado — pulado e descartado: {}", slug, e)
                    tracker.mark_draft(slug, "rejected")
                    dash.mark_skipped(slug, "acesso negado")
                    human_sleep(settings)
                    continue
                except StopRun as e:
                    # Suspeita no Workana → pausa pra intervenção; resolvido = segue p/ próximo.
                    if isinstance(e, SuspiciousActivityError):
                        with dash.paused():
                            resolved = session.handle_suspicious(page, settings, e)
                        if resolved:
                            failed.append((slug, payload, f"interrompido por suspeita (resolvido, não enviado): {e}"))
                            dash.mark_failed(slug, "suspeita (resolvida)")
                            continue
                    aborted = str(e)
                    failed.append((slug, payload, str(e)))
                    dash.mark_failed(slug, str(e)[:50])
                except Exception as e:
                    # inclui SubmitVerificationError → falha por-vaga, draft continua 'pending'.
                    logger.exception("Falha enviando {}: {}", slug, e)
                    failed.append((slug, payload, str(e)))
                    dash.mark_failed(slug, str(e)[:50])

    console.print(
        f"\n[bold]Envio concluído:[/] [green]{sent_n}[/] enviado(s) com sucesso, "
        f"[red]{len(failed)}[/] falhou/falharam (de {len(approved)} aprovado(s))."
    )
    if aborted:
        console.print(f"[bold red]Run abortada:[/] {aborted}")
    if failed:
        report = _write_failure_report(failed, len(approved))
        console.print(f"  → Relatório de falhas: [yellow]{report}[/]")

    tracker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
