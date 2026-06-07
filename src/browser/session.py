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


def ensure_logged_in(context: BrowserContext, jobs_url: str) -> None:
    """Abre o feed; se redirecionar pra login, pede ao usuário fazer login manual."""
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(jobs_url, wait_until="domcontentloaded")
    if "/login" in page.url or "signin" in page.url:
        logger.warning(
            "Sessão não autenticada. Faça login manualmente na janela aberta, "
            "depois volte aqui e aperte ENTER pra continuar."
        )
        input(">>> ENTER após login: ")
        page.goto(jobs_url, wait_until="domcontentloaded")
    logger.info("Sessão OK em {}", page.url)
