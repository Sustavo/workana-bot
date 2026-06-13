import re
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.utils.delays import short_jitter
from src.utils.errors import BidUnavailableError, SubmitVerificationError
from src.utils.number import parse_money

_MIN_BID_RE = re.compile(
    r"(?:lance|valor|or[çc]amento)\s*m[íi]nimo[^R$\d]{0,30}(?:R\$|BRL)?\s*([\d\.\,]+)",
    re.IGNORECASE,
)

# Marcador estruturado da página "Acesso Negado" do Workana (sem form#bidForm).
_ACCESS_DENIED_SEL = "section.error-section, h2.error-title"


@dataclass
class BidPayload:
    amount: float
    delivery_time: str    # "5 dias"
    hours: float | None   # só p/ projeto por hora; senão None
    content: str
    featured_portfolio_ids: list[str]


def open_bid_page(page: Page, job_slug: str) -> None:
    """Abre a página do bid. Se cair em 'Acesso Negado' (vaga sem permissão de lance),
    levanta BidUnavailableError pro caller PULAR a vaga em vez de travar 15s."""
    url = f"https://www.workana.com/messages/bid/{job_slug}"
    page.goto(url, wait_until="domcontentloaded")
    try:
        # corrida: ou o form aparece, ou a página de erro ("Acesso Negado")
        page.wait_for_selector(
            f"form#bidForm, {_ACCESS_DENIED_SEL}", timeout=15_000, state="attached"
        )
    except PWTimeout:
        raise BidUnavailableError(
            "Nem form#bidForm nem página de erro apareceram (timeout).", url=url
        )

    has_form = page.query_selector("form#bidForm") is not None
    denied = page.query_selector(_ACCESS_DENIED_SEL)
    if not has_form:
        title = ""
        el = page.query_selector("h2.error-title")
        if el:
            title = (el.inner_text() or "").strip()
        if denied or title:
            raise BidUnavailableError(f"Acesso Negado: {title or 'sem autorização'}", url=url)
        raise BidUnavailableError("form#bidForm ausente sem página de erro reconhecida.", url=url)

    page.wait_for_selector("form#bidForm", timeout=2_000, state="visible")


def _fmt_amount(amount: float) -> str:
    """Formata o valor pro input#Amount (type=number, formato US/ponto).
    Inteiro → '1050'; com centavos → '150.50'. Evita mandar '1050.0'."""
    if float(amount) == int(amount):
        return str(int(amount))
    return f"{amount:.2f}"


def _set_amount_vue(page: Page, amount: float) -> None:
    """Seta #Amount de forma 'amigável ao Vue': preenche e dispara input+change+blur
    pra forçar o v-model (currentAmount) a sincronizar. Sem isso, o Vue reescreve o
    campo num evento posterior (ex.: vira 2600 ou esvazia)."""
    val = _fmt_amount(amount)
    page.fill("input#Amount", val)
    page.eval_on_selector(
        "input#Amount",
        """(el, v) => {
            el.value = v;
            el.dispatchEvent(new Event('input',  { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur',   { bubbles: true }));
        }""",
        val,
    )


def _read_amount_value(page: Page) -> float | None:
    """Lê o valor atual do #Amount como número (ou None)."""
    v = read_amount_validity(page)
    return parse_money(v.get("value")) if v else None


def read_min_amount(page: Page) -> float | None:
    """Mínimo do bid: maior valor entre input#Amount[min] e texto 'Lance mínimo: R$ X'.
    O atributo `min` é a fonte autoritativa do campo; o texto é cross-check/fallback."""
    candidates: list[float] = []
    attr_min: float | None = None

    el = page.query_selector("input#Amount")
    if el:
        val = el.get_attribute("min")
        if val in (None, ""):
            # 2ª tentativa: ler a propriedade live via JS (alguns layouts setam por JS)
            try:
                val = page.eval_on_selector("input#Amount", "el => el.min")
            except Exception:
                val = None
        if val not in (None, ""):
            v = parse_money(val)
            if v is not None:
                attr_min = v
                candidates.append(v)

    text_min: float | None = None
    try:
        body = page.inner_text("body", timeout=3000)
        m = _MIN_BID_RE.search(body)
        if m:
            v = parse_money(m.group(1))
            if v is not None:
                text_min = v
                candidates.append(v)
                logger.debug("Lance mínimo detectado via texto: R$ {}", v)
    except Exception:
        pass

    if attr_min is not None and text_min is not None and abs(attr_min - text_min) > 0.5:
        logger.warning(
            "Mínimo divergente: atributo={} vs texto={} — usando o maior",
            attr_min, text_min,
        )

    return max(candidates) if candidates else None


def read_amount_validity(page: Page) -> dict | None:
    """Lê o ValidityState nativo do #Amount via JS — a verdade do HTML5.
    Retorna None se o campo não existir/der erro."""
    try:
        return page.eval_on_selector(
            "input#Amount",
            """el => ({
                value: el.value,
                min: el.min,
                valid: el.validity.valid,
                rangeUnderflow: el.validity.rangeUnderflow,
                valueMissing: el.validity.valueMissing,
                badInput: el.validity.badInput,
                stepMismatch: el.validity.stepMismatch
            })""",
        )
    except Exception as e:
        logger.debug("Não consegui ler validity do #Amount: {}", e)
        return None


def clamp_amount(page: Page, intended: float) -> tuple[float, float]:
    """Garante que o valor enviado nunca fique abaixo do mínimo real do Workana.
    Ex.: intended=1000, mínimo=1050 → retorna (1050.0, 1050.0)."""
    min_amt = read_min_amount(page) or 0.0
    final = max(float(intended), min_amt)
    if final != float(intended):
        logger.info("Valor ajustado p/ o mínimo: R$ {:.2f} → R$ {:.2f}", intended, final)
    return final, min_amt


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
    # Ordem importa: o #Amount é preenchido por ÚLTIMO. O form é Vue e preencher
    # #Hours depois do #Amount fazia o Vue reescrever o valor (virava 2600/esvaziava).
    page.fill("textarea#BidContent", payload.content)
    short_jitter()
    if payload.hours is not None:
        hours_el = page.query_selector("input#Hours")
        if hours_el and hours_el.is_visible():
            page.fill("input#Hours", _fmt_amount(payload.hours))
            short_jitter()
    if fill_delivery_time:
        try:
            page.fill("input#BidDeliveryTime", payload.delivery_time)
            short_jitter()
        except Exception:
            logger.debug("Campo BidDeliveryTime ausente (provável form por hora)")
    else:
        logger.debug("Pulando preenchimento de 'Prazo de entrega' (FILL_DELIVERY_TIME=false)")
    # valor por último + dispatch de eventos pro Vue não reescrever
    _set_amount_vue(page, payload.amount)
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


def _click_submit_button(page: Page) -> bool:
    candidates = [
        "form#bidForm input[type='submit'][value='Enviar orçamento']",
        "form#bidForm input[type='submit'].btn-primary",
        "form#bidForm button[type='submit']",
        ".wk-submit-block input[type='submit']",
    ]
    for sel in candidates:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and el.is_enabled():
                el.scroll_into_view_if_needed(timeout=3_000)
                short_jitter()
                el.click()
                logger.info("Clicou em Enviar orçamento (sel='{}')", sel)
                return True
        except PWTimeout:
            continue
    return False


def _click_confirm_modal(page: Page, timeout_ms: int = 4_000) -> bool:
    """Se aparecer o modal de confirmação ('Atenção! … Continuar'), clica Continuar.
    Best-effort: forms sem modal seguem direto. O modal é pré-renderizado mas escondido
    (display:none no ancestral) — por isso exigimos state='visible' (e o texto 'Continuar'
    é único entre os vários modais do form). Retorna True se clicou."""
    try:
        btn = page.wait_for_selector(
            ".modal-footer button.btn-primary:has-text('Continuar')",
            timeout=timeout_ms, state="visible",
        )
    except PWTimeout:
        return False
    try:
        short_jitter()
        btn.click()
        logger.info("Modal de confirmação: cliquei em 'Continuar'")
        return True
    except Exception as e:
        logger.warning("Falha clicando 'Continuar' no modal: {}", e)
        return False


def _has_success_toast(page: Page) -> bool:
    selectors = [
        ".toast-success",
        ".alert-success",
        ".growl-success",
        "text=/proposta enviada|or[çc]amento enviado|enviado com sucesso/i",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            continue
    return False


def _raise_if_form_error(page: Page) -> None:
    """Se houver mensagem de erro de validação visível no form, levanta typed error."""
    selectors = [
        ".help-block.error:visible",
        ".has-error .help-block:visible",
        "#bidForm .error:visible",
        ".field-validation-error:visible",
        "#bidForm .alert-danger:visible",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                msg = (el.inner_text() or "").strip()
                if not msg:
                    continue
                low = msg.lower()
                kind = "below_min" if ("mínimo" in low or "minimo" in low or "min" in low) else "validation"
                raise SubmitVerificationError(f"Form rejeitou: {msg}", kind=kind)
        except SubmitVerificationError:
            raise
        except Exception:
            continue


def submit(page: Page, expected_amount: float | None = None, redirect_timeout_ms: int = 25_000) -> None:
    """Clica em 'Enviar orçamento' e CONFIRMA o envio.

    Contrato: retorna None em sucesso confirmado; levanta SubmitVerificationError
    em qualquer caso não confirmado (valor abaixo do mínimo, sem redirect, erro de
    validação, botão ausente, ou valor que o Vue derivou). Assim o caller NUNCA marca
    como 'sent' um envio que na verdade bugou — causa-raiz do "valor errado / passou e bugou".

    expected_amount: se informado, re-afirma o #Amount logo antes do envio (o Vue pode
    ter reescrito o valor durante skills/portfólio) e ABORTA a vaga se não conseguir fixar.
    """
    # RE-AFIRMAÇÃO DO VALOR: o Vue pode ter reescrito o #Amount (ex.: vira 2600) depois
    # do fill_form, durante skills/portfólio. Garante que o valor certo está no campo.
    if expected_amount is not None:
        cur = _read_amount_value(page)
        if cur is None or abs(cur - float(expected_amount)) > 0.5:
            logger.warning(
                "#Amount derivou (atual={}, esperado={:.2f}) — re-setando antes do envio.",
                cur, float(expected_amount),
            )
            _set_amount_vue(page, expected_amount)
            cur2 = _read_amount_value(page)
            if cur2 is None or abs(cur2 - float(expected_amount)) > 0.5:
                raise SubmitVerificationError(
                    f"Não consegui fixar o valor em R$ {float(expected_amount):.2f} "
                    f"(campo ficou em {cur2}); pulando p/ não enviar valor errado.",
                    kind="amount_drift",
                )

    # PRÉ-CHECK: validade HTML5 antes de clicar (pega valor abaixo do mínimo)
    v = read_amount_validity(page)
    if v is not None:
        if v.get("rangeUnderflow"):
            raise SubmitVerificationError(
                f"Valor R$ {v.get('value')} abaixo do mínimo {v.get('min')} — HTML5 bloquearia o envio.",
                kind="below_min",
            )
        if v.get("valueMissing"):
            raise SubmitVerificationError("Campo de valor vazio.", kind="validation")
        if not v.get("valid"):
            raise SubmitVerificationError(
                f"#Amount inválido (value={v.get('value')}, validity={v}).",
                kind="validation",
            )

    if not _click_submit_button(page):
        raise SubmitVerificationError(
            "Nenhum botão 'Enviar orçamento' clicável encontrado no form.",
            kind="no_button",
        )

    # Modal de confirmação ('Atenção! … Continuar'), quando aparece (ex.: projeto por hora).
    _click_confirm_modal(page)

    # PÓS-CHECK: confirmar de verdade
    url_before = page.url
    try:
        page.wait_for_function(
            "u => location.href !== u", arg=url_before, timeout=redirect_timeout_ms,
        )
    except PWTimeout:
        # Sem redirect: pode ser SPA com toast de sucesso OU erro silencioso.
        if _has_success_toast(page):
            logger.success("Envio confirmado via toast de sucesso")
            return
        _raise_if_form_error(page)  # levanta below_min/validation se achar mensagem
        v2 = read_amount_validity(page)
        if v2 is not None and v2.get("rangeUnderflow"):
            raise SubmitVerificationError(
                f"Bloqueado pelo mínimo após click (value={v2.get('value')}, min={v2.get('min')}).",
                kind="below_min",
            )
        raise SubmitVerificationError(
            "Sem redirect e sem toast de sucesso após 'Enviar orçamento' — envio NÃO confirmado.",
            kind="no_redirect",
        )

    # Houve mudança de URL: garantir que não ficou na própria página /bid/ com erro
    if "/messages/bid/" in (page.url or "").lower():
        _raise_if_form_error(page)
        raise SubmitVerificationError(
            "Continua na página /bid/ após submit — envio não confirmado.",
            kind="no_redirect",
        )

    logger.success("Envio confirmado — redirecionou pra {}", page.url)
