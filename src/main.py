"""CLI principal: scraping + geração de drafts. Não envia nada."""
from dataclasses import asdict

import click
from loguru import logger

from src.ai.generator import generate
from src.browser import guard, session
from src.db.tracker import Tracker
from src.filters.matcher import passes, passes_detail
from src.scraper import job_detail, job_insight, jobs_list, profile
from src.ui.dashboard import Dashboard, DashState
from src.utils.config import SPEED_PRESETS, Settings, load_filters, load_profile
from src.utils.delays import human_sleep
from src.utils.errors import AIFatalError, StopRun, SuspiciousActivityError
from src.utils.logger import setup_logger


@click.group()
def cli() -> None:
    pass


def _react_to_stop(e: Exception, page, settings: Settings, dash: Dashboard) -> str | None:
    """Decide o que fazer com um StopRun. Retorna motivo de ABORT (str) ou None se
    foi resolvido (pode continuar). Comportamento inteligente (decisão do usuário):
    - IA fatal (DeepSeek) → aborta (não adianta continuar).
    - Atividade suspeita → pausa e espera intervenção; se resolvida, continua."""
    if isinstance(e, AIFatalError):
        return f"erro fatal da IA (DeepSeek): {e}"
    if isinstance(e, SuspiciousActivityError):
        with dash.paused():
            resolved = session.handle_suspicious(page, settings, e)
        return None if resolved else f"atividade suspeita: {e}"
    return f"parada: {e}"


@cli.command()
@click.option(
    "--speed",
    type=click.Choice(list(SPEED_PRESETS.keys())),
    default=None,
    help="Perfil de velocidade (sobrepõe SPEED_PROFILE do .env).",
)
def scrape(speed: str | None) -> None:
    """Lê o feed, filtra, gera drafts e salva em data/pending/ (via SQLite)."""
    settings = Settings.load(speed_override=speed)
    setup_logger(settings)
    logger.info("IA: {}", settings.ai_summary())
    logger.info("Velocidade: {}", settings.speed_summary())
    filters = load_filters()
    profile_data = load_profile()
    tracker = Tracker(settings.database_path)

    state = DashState(
        phase="scrape",
        speed_profile=settings.speed_profile,
        total=settings.max_drafts_per_run,
    )
    drafted = 0
    aborted_reason: str | None = None

    # Vagas que JÁ têm draft (pendente/enviado/rejeitado) — nunca re-enfileirar.
    existing_drafts = tracker.all_draft_slugs()
    sm = tracker.summary()
    dft = sm["drafts"]
    jbs = sm["jobs"]
    logger.info(
        "📂 Banco: {} vagas já com draft ({} pendentes, {} enviadas, {} rejeitadas) — "
        "não serão re-enfileiradas | abertas: {}, puladas: {}",
        len(existing_drafts), dft.get("pending", 0), dft.get("sent", 0), dft.get("rejected", 0),
        jbs.get("open", 0), jbs.get("skipped", 0),
    )

    with session.open_context(settings) as ctx:
        session.ensure_logged_in(ctx, settings.workana_jobs_url)
        page = ctx.pages[0]

        if settings.workana_user_id:
            try:
                conn = profile.scrape_connections(page, settings.workana_user_id)
                state.connections_left = conn.available
                logger.info("Conexões disponíveis: {} (raw='{}')", conn.available, conn.raw)
            except Exception as e:
                logger.warning("Falha lendo conexões: {}", e)
            human_sleep(settings)

        with Dashboard(state, settings, enabled=not settings.headless) as dash:
            page_num = 1
            stop = False
            seen_slugs: set[str] = set()
            while not stop:
                sep = "&" if "?" in settings.workana_jobs_url else "?"
                page_url = (
                    settings.workana_jobs_url
                    if page_num == 1
                    else f"{settings.workana_jobs_url}{sep}page={page_num}"
                )
                logger.info("→ Página {}", page_num)
                try:
                    if settings.guard_enabled:
                        guard.goto_checked(page, page_url, "feed")
                    else:
                        page.goto(page_url, wait_until="domcontentloaded")
                except StopRun as e:
                    aborted_reason = _react_to_stop(e, page, settings, dash)
                    if aborted_reason:
                        break
                    continue  # bloqueio resolvido → re-tenta a mesma página

                cards = jobs_list.scrape_page(page)
                reason = jobs_list.feed_exhausted(cards, seen_slugs)
                if reason:
                    logger.info("Página {} — {} → fim dos resultados reais, parando.", page_num, reason)
                    break
                seen_slugs.update(c.slug for c in cards)

                for card in cards:
                    if drafted >= settings.max_drafts_per_run:
                        logger.info("Limite de drafts ({}) atingido", settings.max_drafts_per_run)
                        stop = True
                        break
                    card_state = "open" if card.has_open_bid else "already_bid"
                    tracker.upsert_job(card.slug, card.title, card.url, card_state)
                    if not card.has_open_bid:
                        logger.info("Pulando {} ({})", card.slug, card.action_text)
                        continue
                    # Dedup direto pela tabela de drafts: já tem draft → não re-enfileira.
                    if card.slug in existing_drafts:
                        logger.info("Já tem draft pra {} — pulando (não re-enfileira)", card.slug)
                        continue
                    ok, reason = passes(card, filters, profile_data)
                    if not ok:
                        tracker.upsert_job(card.slug, card.title, card.url, "skipped")
                        logger.info("Filtrado: {} → {}", card.slug, reason)
                        dash.mark_skipped(card.slug, reason)
                        continue

                    dash.start_job(card.slug, card.title)
                    try:
                        detail = job_detail.scrape(page, card.url)
                        if settings.guard_enabled:
                            guard.assert_safe(page, "job_detail")
                        ok2, reason2 = passes_detail(detail, filters, profile_data)
                        if not ok2:
                            tracker.upsert_job(card.slug, card.title, card.url, "skipped")
                            logger.info("Filtrado (detalhe): {} → {}", card.slug, reason2)
                            dash.mark_skipped(card.slug, reason2)
                            continue
                        human_sleep(settings)
                        insight = job_insight.scrape(page, card.slug)
                        if settings.guard_enabled:
                            guard.assert_safe(page, "job_insight")
                        human_sleep(settings)
                        gen = generate(settings, asdict(detail), asdict(insight))
                    except StopRun as e:
                        aborted_reason = _react_to_stop(e, page, settings, dash)
                        if aborted_reason:
                            stop = True
                            break
                        continue  # bloqueio resolvido → pula esta vaga e segue
                    except Exception as e:
                        logger.exception("Erro por-vaga em {}: {}", card.slug, e)
                        dash.mark_skipped(card.slug, str(e)[:50])
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
                    existing_drafts.add(card.slug)
                    drafted += 1
                    dash.mark_generated(card.slug, gen.amount_brl, insight.avg_bid_value)
                    logger.success(
                        "Draft gerado: {} (R$ {:.2f}, {})",
                        card.slug, gen.amount_brl, gen.delivery_time,
                    )

                if stop:
                    break
                page_num += 1

    tracker.close()
    if aborted_reason:
        logger.error(
            "Run ABORTADA ({}). {} draft(s) gerados antes de parar. Rode `python approve.py` pra revisar.",
            aborted_reason, drafted,
        )
    else:
        logger.info(
            "Fim — {} drafts gerados nesta run. Rode `python approve.py` pra revisar.",
            drafted,
        )


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
