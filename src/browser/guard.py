"""Detector de bloqueio / atividade suspeita do Workana.

O Workana usa Cloudflare (Turnstile) e pode disparar captcha / página de
"atividade suspeita" / redirect pro login no meio da run. Insistir nesses
casos é o caminho mais rápido pro ban. Este módulo detecta esses sinais e
levanta SuspiciousActivityError pra automação parar (e, no caller, pausar
pedindo intervenção manual).
"""
from __future__ import annotations

from loguru import logger
from playwright.sync_api import Page, Response

from src.utils.errors import SuspiciousActivityError

# Textos que aparecem em páginas de challenge/bloqueio.
_BLOCK_TEXT_MARKERS = (
    "verifying you are human",
    "verify you are human",
    "atividade suspeita",
    "unusual activity",
    "unusual traffic",
    "acesso negado",
    "access denied",
    "you have been blocked",
    "checking your browser before accessing",
    "too many requests",
    "rate limit",
    "tente novamente mais tarde",
)

# Títulos típicos de página de challenge do Cloudflare.
_BLOCK_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "access denied",
    "um momento",
)

# Iframes / elementos de challenge ou captcha.
_CHALLENGE_SELECTORS = (
    "iframe[src*='challenges.cloudflare.com']",  # Turnstile
    "iframe[title*='challenge']",
    "iframe[src*='recaptcha']",
    ".g-recaptcha",
    "div.h-captcha",
    "iframe[src*='hcaptcha']",
    "#cf-challenge-running",
    "#challenge-form",
    "form#captcha",
)

_BAD_STATUS = {403, 429, 503}


def detect_block(page: Page, context: str = "", check_login_redirect: bool = True) -> str | None:
    """Retorna o motivo do bloqueio, ou None se a página parece normal. Não levanta."""
    url = (page.url or "").lower()

    if check_login_redirect and ("/login" in url or "/signin" in url):
        return f"redirecionado pra login ({url})"

    for sel in _CHALLENGE_SELECTORS:
        try:
            if page.query_selector(sel):
                return f"challenge/captcha detectado (sel={sel})"
        except Exception:
            pass

    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    for marker in _BLOCK_TITLE_MARKERS:
        if marker in title:
            return f"título de bloqueio: '{title}'"

    try:
        body = page.inner_text("body", timeout=2500).lower()
    except Exception:
        body = ""
    for marker in _BLOCK_TEXT_MARKERS:
        if marker in body:
            return f"texto de bloqueio: '{marker}'"

    return None


def assert_safe(page: Page, context: str = "", check_login_redirect: bool = True) -> None:
    """Levanta SuspiciousActivityError se detectar bloqueio na página atual."""
    reason = detect_block(page, context, check_login_redirect=check_login_redirect)
    if reason:
        logger.error("[guard:{}] bloqueio detectado: {}", context, reason)
        raise SuspiciousActivityError(f"[{context}] {reason}", url=page.url)


def goto_checked(
    page: Page,
    url: str,
    context: str = "",
    wait_until: str = "domcontentloaded",
    timeout: int = 30_000,
    check_login_redirect: bool = True,
) -> Response | None:
    """page.goto + checagem de status HTTP + assert_safe. Levanta em bloqueio."""
    resp = page.goto(url, wait_until=wait_until, timeout=timeout)
    if resp is not None and resp.status in _BAD_STATUS:
        logger.error("[guard:{}] HTTP {} em {}", context, resp.status, url)
        raise SuspiciousActivityError(f"[{context}] HTTP {resp.status}", url=url)
    assert_safe(page, context, check_login_redirect=check_login_redirect)
    return resp
