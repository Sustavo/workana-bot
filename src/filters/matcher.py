import re

from src.scraper.jobs_list import JobCard


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def passes(card: JobCard, filters: dict, profile: dict) -> tuple[bool, str]:
    """Retorna (ok, motivo). motivo só preenchido quando ok=False."""
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

    return True, ""
