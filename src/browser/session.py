from contextlib import contextmanager
from typing import Iterator

from loguru import logger
from playwright.sync_api import BrowserContext, sync_playwright

from src.utils.config import Settings


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@contextmanager
def open_context(settings: Settings) -> Iterator[BrowserContext]:
    settings.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(settings.chrome_profile_dir),
            headless=settings.headless,
            channel="chrome",
            user_agent=USER_AGENT,
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
