import re
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.utils.delays import short_jitter

_MIN_BID_RE = re.compile(
    r"(?:lance|valor|or[çc]amento)\s*m[íi]nimo[^R$\d]{0,30}(?:R\$|BRL)?\s*([\d\.\,]+)",
    re.IGNORECASE,
)


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


def _parse_amount(text: str) -> float | None:
    """Parseia '7.331,00' (BR), '7331.00' (US), '7.331' (milhar BR), '160' etc."""
    if not text:
        return None
    s = text.strip()
    has_comma = "," in s
    if has_comma:
        s = s.replace(".", "").replace(",", ".")
    else:
        if "." in s:
            tail = s.rsplit(".", 1)[1]
            if len(tail) == 3:
                s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def read_min_amount(page: Page) -> float | None:
    """Mínimo do bid: maior valor entre input#Amount[min] e texto 'Lance mínimo: R$ X'."""
    candidates: list[float] = []

    el = page.query_selector("input#Amount")
    if el:
        val = el.get_attribute("min")
        if val:
            try:
                candidates.append(float(val))
            except ValueError:
                pass

    try:
        body = page.inner_text("body", timeout=3000)
        m = _MIN_BID_RE.search(body)
        if m:
            v = _parse_amount(m.group(1))
            if v:
                candidates.append(v)
                logger.debug("Lance mínimo detectado via texto: R$ {}", v)
    except Exception:
        pass

    return max(candidates) if candidates else None


def is_hourly_form(page: Page) -> bool:
    """Detecta 'Valor total por hora' (projeto por hora) no label perto de #Amount."""
    try:
        for lbl in page.query_selector_all("label.wk-bullet"):
            text = (lbl.inner_text() or "").lower()
            if "por hora" in text:
                return True
    except Exception:
        pass
    return False


def ensure_skill_selected(page: Page, fallback_skill: str) -> bool:
    """Garante pelo menos 1 skill marcada. Estratégias em ordem:
    1) Já tem skills selecionadas → ok.
    2) Clica num chip visível e não-selecionado (Workana costuma sugerir vários).
    3) Digita no campo de busca e clica num item do dropdown.
    NUNCA pressiona Enter (isso pula pro próximo passo e quebra o fluxo)."""
    selected = page.query_selector_all("label.skill.like-chip.selected, label.skill.selected")
    if selected:
        logger.debug("{} skills já selecionadas — ok", len(selected))
        return True

    chips = page.query_selector_all("label.skill.like-chip:not(.selected), label.skill:not(.selected)")
    for chip in chips:
        try:
            if not chip.is_visible():
                continue
            chip.scroll_into_view_if_needed(timeout=2000)
            short_jitter()
            chip.click()
            txt = (chip.inner_text() or "").strip()
            logger.info("Skill chip clicado: '{}'", txt[:40])
            return True
        except Exception:
            continue

    search = page.query_selector("input.multi-select-search-field, input[placeholder*='Pesquisar habilidade']")
    if not search:
        logger.warning("Sem chips visíveis e sem campo 'Pesquisar habilidade' — pulando skills")
        return False

    try:
        search.scroll_into_view_if_needed(timeout=2000)
        search.click()
        short_jitter()
        search.fill(fallback_skill)
        page.wait_for_timeout(1200)

        dropdown_selectors = [
            ".multi-select-options li:visible",
            ".multi-select-search-results li:visible",
            ".dropdown-menu li:visible",
            "ul.suggestions li:visible",
            ".skills-for-steps li:not(.multi-select-search):visible",
            ".skills-select li:not(.multi-select-search):visible",
            ".tt-suggestion:visible",
            ".autocomplete-suggestion:visible",
        ]
        for sel in dropdown_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    logger.info("Skill via dropdown '{}'", sel)
                    return True
            except Exception:
                continue

        dump_dir = Path("data/insights/debug")
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump = dump_dir / f"skill-fail-{int(time.time())}.html"
        try:
            dump.write_text(page.content(), encoding="utf-8")
        except Exception:
            pass
        logger.warning(
            "Nenhum dropdown de skill encontrado após digitar '{}'. HTML salvo em {}",
            fallback_skill, dump,
        )
        return False
    except Exception as e:
        logger.warning("Falha adicionando skill fallback '{}': {}", fallback_skill, e)
        return False


def fill_form(page: Page, payload: BidPayload, fill_delivery_time: bool = False) -> None:
    page.fill("textarea#BidContent", payload.content)
    short_jitter()
    page.fill("input#Amount", str(payload.amount))
    short_jitter()
    if fill_delivery_time:
        try:
            page.fill("input#BidDeliveryTime", payload.delivery_time)
            short_jitter()
        except Exception:
            logger.debug("Campo BidDeliveryTime ausente (provável form por hora)")
    else:
        logger.debug("Pulando preenchimento de 'Prazo de entrega' (FILL_DELIVERY_TIME=false)")
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
    """Clica em 'Enviar orçamento' e espera o redirect (sai da página /bid/)."""
    candidates = [
        "form#bidForm input[type='submit'][value='Enviar orçamento']",
        "form#bidForm input[type='submit'].btn-primary",
        "form#bidForm button[type='submit']",
        ".wk-submit-block input[type='submit']",
    ]
    clicked = False
    for sel in candidates:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.scroll_into_view_if_needed(timeout=3_000)
                short_jitter()
                el.click()
                logger.info("Clicou em Enviar orçamento (sel='{}')", sel)
                clicked = True
                break
        except PWTimeout:
            continue
    if not clicked:
        raise RuntimeError(
            "Nenhum botão 'Enviar orçamento' clicável encontrado no form. "
            "Verifique se o form mudou."
        )

    url_before = page.url
    try:
        page.wait_for_function(
            "url => location.href !== url",
            arg=url_before,
            timeout=20_000,
        )
        logger.info("Redirecionado pra {}", page.url)
    except PWTimeout:
        logger.warning("Sem redirect após click em 'Enviar orçamento' — verifique manualmente")
