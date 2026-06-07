from dataclasses import dataclass

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.utils.delays import short_jitter


@dataclass
class BidPayload:
    amount: float
    delivery_time: str    # "5 dias"
    hours: float | None   # só p/ projeto por hora; senão None
    content: str
    featured_portfolio_ids: list[str]


def open_bid_page(page: Page, job_slug: str) -> None:
    url = f"https://www.workana.com/messages/bid/{job_slug}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("form#bidForm", timeout=15_000)


def read_min_amount(page: Page) -> float | None:
    el = page.query_selector("input#Amount")
    if not el:
        return None
    val = el.get_attribute("min")
    try:
        return float(val) if val else None
    except ValueError:
        return None


def fill_form(page: Page, payload: BidPayload) -> None:
    page.fill("textarea#BidContent", payload.content)
    short_jitter()
    page.fill("input#Amount", str(payload.amount))
    short_jitter()
    page.fill("input#BidDeliveryTime", payload.delivery_time)
    short_jitter()
    if payload.hours is not None:
        hours_el = page.query_selector("input#Hours")
        if hours_el and hours_el.is_visible():
            page.fill("input#Hours", str(payload.hours))
            short_jitter()


def select_portfolio(page: Page, ids: list[str]) -> bool:
    """Abre o modal de portfólio e seleciona até 3 itens pelos IDs.
    Retorna False se a etapa não conseguiu — caller decide se ainda envia."""
    if not ids:
        logger.warning("Sem featured_portfolio_ids configurados — pulando seleção de destaques")
        return False
    try:
        page.click("button#portfolioOpenBidDialog", timeout=5_000)
    except PWTimeout:
        logger.warning("Botão 'Buscar no portfólio' não encontrado")
        return False
    page.wait_for_selector(".modal.in, .modal.show", timeout=5_000)
    short_jitter()
    picked = 0
    for pid in ids[:3]:
        candidates = [
            f".modal [data-id='{pid}']",
            f".modal [data-portfolio-id='{pid}']",
            f".modal [data-project-id='{pid}']",
        ]
        clicked = False
        for sel in candidates:
            el = page.query_selector(sel)
            if el:
                el.click()
                clicked = True
                picked += 1
                short_jitter()
                break
        if not clicked:
            logger.warning("Portfolio id {} não encontrado no modal", pid)
    # botão de confirmar do modal — texto varia, tento alguns
    for sel in [
        ".modal .btn-primary:not([disabled])",
        ".modal button:has-text('Selecionar')",
        ".modal button:has-text('Confirmar')",
    ]:
        btn = page.query_selector(sel)
        if btn:
            btn.click()
            break
    short_jitter()
    return picked >= 3


def submit(page: Page) -> None:
    """Clica em 'Continuar' e confirma no modal."""
    page.click("form#bidForm button.btn-primary:has-text('Continuar')")
    # Modal de confirmação aparece
    page.wait_for_selector(".modal.in, .modal.show", timeout=10_000)
    short_jitter()
    # Confirma — geralmente 'Enviar' ou 'Confirmar' dentro do modal
    confirm_selectors = [
        ".modal button:has-text('Enviar')",
        ".modal button:has-text('Confirmar')",
        ".modal .btn-primary",
    ]
    for sel in confirm_selectors:
        btn = page.query_selector(sel)
        if btn and btn.is_enabled():
            btn.click()
            logger.info("Proposta enviada (confirm sel='{}')", sel)
            break
    # Após envio, Workana redireciona pra inbox
    page.wait_for_url("**/inbox/**", timeout=15_000)
