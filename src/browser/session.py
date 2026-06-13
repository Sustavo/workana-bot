from contextlib import contextmanager
from typing import Iterator

from loguru import logger
from playwright.sync_api import BrowserContext, sync_playwright

from src.browser import guard
from src.utils.config import Settings
from src.utils.errors import SuspiciousActivityError


@contextmanager
def open_context(settings: Settings) -> Iterator[BrowserContext]:
    settings.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # Sem user_agent fixo: com channel="chrome" o próprio Chrome usa o UA real,
        # evitando o descompasso "Chrome/131 fixo vs Chrome instalado" (fingerprint).
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(settings.chrome_profile_dir),
            headless=settings.headless,
            channel="chrome",
            viewport={"width": 1366, "height": 850},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=["--disable-blink-features=AutomationControlled"],
        )
        logger.info("Browser aberto (profile={})", settings.chrome_profile_dir)
        try:
            yield context
        finally:
            context.close()
            logger.info("Browser fechado")


def _is_authenticated(page) -> bool:
    """Vai pro /dashboard: deslogado redireciona pra /login, logado fica em /dashboard."""
    try:
        page.goto("https://www.workana.com/dashboard", wait_until="domcontentloaded", timeout=15_000)
    except Exception as e:
        logger.debug("Falha indo pra /dashboard: {}", e)
        return False
    url = page.url.lower()
    return "/dashboard" in url and "/login" not in url and "signin" not in url


def ensure_logged_in(context: BrowserContext, jobs_url: str) -> None:
    """Verifica sessão autenticada via /dashboard; se anônimo, pausa pra login manual."""
    page = context.pages[0] if context.pages else context.new_page()

    for _ in range(3):
        if _is_authenticated(page):
            page.goto(jobs_url, wait_until="domcontentloaded")
            logger.info("Sessão OK em {}", page.url)
            return
        logger.warning(
            "Sessão NÃO autenticada (/dashboard redirecionou pra login). "
            "Faça login manualmente na janela aberta. ENTER aqui após logar."
        )
        input(">>> ENTER após login: ")

    raise RuntimeError(
        "Sessão Workana continua anônima depois de 3 tentativas. "
        "Verifique o login no browser e rode de novo."
    )


def handle_suspicious(page, settings: Settings, err: SuspiciousActivityError) -> bool:
    """Trata atividade suspeita do Workana de forma INTELIGENTE (decisão do usuário):
    pausa e espera intervenção manual (captcha/login), re-checa e continua.

    Retorna True se o bloqueio foi resolvido (pode continuar); False se deve abortar
    (modo headless/não-interativo ou ainda bloqueado após a intervenção).

    IMPORTANTE: chame com o dashboard PAUSADO (Live parado), senão o input() conflita.
    """
    reason = getattr(err, "reason", str(err))
    if settings.headless:
        logger.error("Atividade suspeita em modo headless — abortando: {}", reason)
        return False

    logger.warning("⚠️  Atividade suspeita detectada no Workana: {}", reason)
    print(
        "\n⚠️  O Workana sinalizou algo suspeito (captcha/login/bloqueio).\n"
        "    Resolva manualmente na janela do browser e tecle ENTER pra continuar\n"
        "    (ou Ctrl+C pra abortar a automação).\n"
    )
    try:
        input(">>> ENTER após resolver: ")
    except (EOFError, KeyboardInterrupt):
        logger.error("Intervenção cancelada — abortando.")
        return False

    still = guard.detect_block(page, "pós-intervenção")
    if still:
        logger.error("Ainda bloqueado após intervenção ({}) — abortando.", still)
        return False
    logger.info("Bloqueio resolvido — retomando a automação.")
    return True
