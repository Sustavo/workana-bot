import re

from src.scraper.jobs_list import JobCard
from src.utils.number import parse_money_max


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


# Conectores ignorados ao comparar nomes de categoria (robusto a ordem/idioma).
_CAT_STOP = {"e", "&", "and", "y"}


def _cat_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[\s/&]+", _norm(s)) if t and t not in _CAT_STOP}


def _cat_match(filter_cat: str, actual_cat: str) -> bool:
    """Casa nomes de categoria por conjunto de tokens (ignora ordem e conector).
    'Vendas e Marketing' casa com 'Marketing e Vendas'; 'Design' casa com
    'Design & Multimedia' (subconjunto)."""
    ft, at = _cat_tokens(filter_cat), _cat_tokens(actual_cat)
    return bool(ft) and bool(at) and (ft == at or ft.issubset(at))


def passes(card: JobCard, filters: dict, profile: dict) -> tuple[bool, str]:
    """Filtro no nível do CARD (barato, roda antes de abrir o detalhe).
    Retorna (ok, motivo). motivo só preenchido quando ok=False."""
    if not card.has_open_bid:
        return False, "ja propus / sem botão de proposta"

    text = _norm(card.title) + " " + " ".join(_norm(s) for s in card.skills)

    for kw in filters.get("blocked_keywords") or []:
        if _norm(kw) in text:
            return False, f"keyword bloqueada: {kw}"

    for kw in profile.get("do_not_take") or []:
        if _norm(kw) in text:
            return False, f"do_not_take: {kw}"

    req = filters.get("required_keywords_any") or []
    if req and not any(_norm(k) in text for k in req):
        return False, "nenhuma keyword obrigatória presente"

    # Vagas saturadas: pula se já tem propostas demais (quando o card informa).
    max_props = filters.get("max_competing_proposals")
    if max_props and card.bids_count is not None and card.bids_count > int(max_props):
        return False, f"saturada: {card.bids_count} propostas (> {max_props})"

    # Orçamento mínimo (quando o card mostra orçamento — nem todo card mostra).
    min_budget = filters.get("min_budget_usd")
    if min_budget and card.budget_value is not None and card.budget_value < float(min_budget):
        return False, f"orçamento baixo: {card.budget_value:.0f} (< {min_budget})"

    return True, ""


def passes_detail(detail, filters: dict, profile: dict) -> tuple[bool, str]:
    """Filtro no nível do DETALHE da vaga (categoria e orçamento aparecem aqui).
    Roda depois de job_detail.scrape, antes de gerar a proposta."""
    cat = getattr(detail, "category", "")

    allowed = filters.get("allowed_categories") or []
    if allowed and cat and not any(_cat_match(a, cat) for a in allowed):
        return False, f"categoria fora da lista permitida: {cat}"

    for c in (filters.get("blocked_categories") or []):
        if cat and _cat_match(c, cat):
            return False, f"categoria bloqueada: {cat}"

    min_budget = filters.get("min_budget_usd")
    if min_budget:
        budget_val = parse_money_max(getattr(detail, "budget_text", ""))
        if budget_val is not None and budget_val < float(min_budget):
            return False, f"orçamento baixo: {budget_val:.0f} (< {min_budget})"

    return True, ""
