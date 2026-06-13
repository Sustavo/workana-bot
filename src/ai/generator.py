import json
import re
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger

from src.ai.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from src.utils.config import Settings, load_examples, load_profile
from src.utils.errors import GeminiFatalError


@dataclass
class GeneratedProposal:
    content: str
    amount_brl: float
    delivery_time: str
    hours_estimate: float | None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Códigos HTTP de ClientError que NÃO adianta continuar (auth/quota) → abortar.
_FATAL_CLIENT_CODES = {401, 403, 429}
_FATAL_STR_MARKERS = (
    "resource_exhausted", "resourceexhausted", "429", "quota", "permission_denied",
    "permissiondenied", "unauthenticated", "api key", "api_key", "503",
    "service_unavailable", "serviceunavailable", "rate limit", "exceeded",
)


def _is_fatal_genai_error(e: Exception) -> bool:
    """True quando não adianta continuar (quota/auth/serviço fora) → abortar a run.
    Erros 4xx de request malformado (ex.: 400) são por-vaga (retornam False)."""
    # 5xx do servidor (503 ServiceUnavailable, 500 etc.) → fatal
    if isinstance(e, genai_errors.ServerError):
        return True
    # 4xx: só auth/quota são fatais
    if isinstance(e, genai_errors.ClientError):
        code = getattr(e, "code", None)
        if code in _FATAL_CLIENT_CODES:
            return True
        s = f"{getattr(e, 'message', '')} {e}".lower()
        return any(k in s for k in _FATAL_STR_MARKERS)
    # fallback por string (erros de transporte/timeout, mudanças de versão)
    s = f"{type(e).__name__}: {e}".lower()
    return any(k in s for k in _FATAL_STR_MARKERS)


def _profile_block(profile: dict) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)


def _build_system(profile: dict, examples: str) -> str:
    return f"""{SYSTEM_INSTRUCTION}

## PERFIL DO FREELANCER (fixo, não muda entre vagas)
```json
{_profile_block(profile)}
```

## EXEMPLOS DE PROPOSTAS QUE FUNCIONARAM
{examples or "(sem exemplos)"}
"""


def generate(settings: Settings, job: dict, insight: dict | None) -> GeneratedProposal:
    profile = load_profile()
    examples = load_examples()
    system = _build_system(profile, examples)
    discount = float(profile.get("bid_discount_pct", 0.10))

    client = genai.Client(api_key=settings.google_api_key)
    user_prompt = build_user_prompt(job, insight, discount)
    logger.debug("Prompt user ({} chars): {}", len(user_prompt), user_prompt[:200])

    try:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.6,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:
        if _is_fatal_genai_error(e):
            raise GeminiFatalError(
                f"Erro fatal da API Gemini ({type(e).__name__}): {e}"
            ) from e
        raise  # demais erros: tratados como por-vaga no caller

    raw = (getattr(resp, "text", None) or "")
    if not raw.strip():
        # resposta vazia/bloqueada por safety → por-vaga (pula), não é fatal
        raise ValueError("Gemini retornou resposta vazia (possível bloqueio de safety)")
    match = _JSON_RE.search(raw)
    data = json.loads(match.group(0) if match else raw)

    amount_brl = float(data["amount_brl"])
    avg = (insight or {}).get("avg_bid_value")
    if avg:
        target = round(float(avg) * (1 - discount))
        if abs(target - amount_brl) > 0.5:
            logger.info(
                "Override amount_brl: Gemini={} → target={} (avg={} desc={:.0%})",
                amount_brl, target, avg, discount,
            )
        amount_brl = float(target)

    max_bid = profile.get("max_bid_brl")
    if max_bid and amount_brl > float(max_bid):
        logger.warning(
            "Cap amount_brl: {} → {} (max_bid_brl do profile)",
            amount_brl, max_bid,
        )
        amount_brl = float(max_bid)

    return GeneratedProposal(
        content=data["content"].strip(),
        amount_brl=amount_brl,
        delivery_time=str(data.get("delivery_time") or "5 dias"),
        hours_estimate=(float(data["hours_estimate"]) if data.get("hours_estimate") is not None else None),
    )
