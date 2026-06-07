"""CLI principal: scraping + geração de drafts. Não envia nada."""
from dataclasses import asdict

import click
from loguru import logger

from src.ai.generator import generate
from src.browser.session import ensure_logged_in, open_context
from src.db.tracker import Tracker
from src.filters.matcher import passes
from src.scraper import job_detail, job_insight, jobs_list, profile
from src.utils.config import Settings, load_filters, load_profile
from src.utils.delays import human_sleep
from src.utils.logger import setup_logger


@click.group()
def cli() -> None:
    pass


@cli.command()
def scrape() -> None:
    """Lê o feed, filtra, gera drafts e salva em data/pending/ (via SQLite)."""
    settings = Settings.load()
    setup_logger(settings)
    filters = load_filters()
    profile_data = load_profile()
    tracker = Tracker(settings.database_path)

    with open_context(settings) as ctx:
        ensure_logged_in(ctx, settings.workana_jobs_url)
        page = ctx.pages[0]

        if settings.workana_user_id:
            try:
                conn = profile.scrape_connections(page, settings.workana_user_id)
                logger.info("Conexões disponíveis: {} (raw='{}')", conn.available, conn.raw)
            except Exception as e:
                logger.warning("Falha lendo conexões: {}", e)
            human_sleep(settings)

        drafted = 0
        page_num = 1
        stop = False
        while not stop:
            sep = "&" if "?" in settings.workana_jobs_url else "?"
            page_url = (
                settings.workana_jobs_url
                if page_num == 1
                else f"{settings.workana_jobs_url}{sep}page={page_num}"
            )
            page.goto(page_url, wait_until="domcontentloaded")
            cards = jobs_list.scrape_page(page)
            if not cards:
                logger.info("Página {} sem cards — fim do feed", page_num)
                break

            for card in cards:
                if drafted >= settings.max_drafts_per_run:
                    logger.info("Limite de drafts ({}) atingido", settings.max_drafts_per_run)
                    stop = True
                    break
                state = "open" if card.has_open_bid else "already_bid"
                tracker.upsert_job(card.slug, card.title, card.url, state)
                if not card.has_open_bid:
                    logger.info("Pulando {} ({})", card.slug, card.action_text)
                    continue
                ok, reason = passes(card, filters, profile_data)
                if not ok:
                    tracker.upsert_job(card.slug, card.title, card.url, "skipped")
                    logger.info("Filtrado: {} → {}", card.slug, reason)
                    continue
                if tracker.job_state(card.slug) in {"drafted", "sent"}:
                    logger.info("Já tem draft/envio pra {}", card.slug)
                    continue

                try:
                    detail = job_detail.scrape(page, card.url)
                    human_sleep(settings)
                    insight = job_insight.scrape(page, card.slug)
                    human_sleep(settings)
                    gen = generate(settings, asdict(detail), asdict(insight))
                except Exception as e:
                    logger.exception("Erro coletando/gerando pra {}: {}", card.slug, e)
                    continue

                payload = {
                    "job": asdict(detail),
                    "insight": asdict(insight),
                    "proposal": {
                        "content": gen.content,
                        "amount_brl": gen.amount_brl,
                        "delivery_time": gen.delivery_time,
                        "hours_estimate": gen.hours_estimate,
                    },
                    "card": asdict(card),
                }
                tracker.save_draft(card.slug, payload)
                tracker.upsert_job(card.slug, card.title, card.url, "drafted")
                drafted += 1
                logger.success("Draft gerado: {} (R$ {:.2f}, {})", card.slug, gen.amount_brl, gen.delivery_time)

            if stop:
                break
            page_num += 1

    tracker.close()
    logger.info("Fim. Drafts pendentes para revisão: rode `python approve.py`")


@cli.command()
def list_drafts() -> None:
    """Mostra drafts pendentes (sem abrir browser)."""
    settings = Settings.load()
    setup_logger(settings)
    tracker = Tracker(settings.database_path)
    for d in tracker.list_pending_drafts():
        print(f"- {d['slug']} ({d['created_at']})")
        print(f"    R$ {d['payload']['proposal']['amount_brl']:.2f} | {d['payload']['proposal']['delivery_time']}")
    tracker.close()


if __name__ == "__main__":
    cli()
