import json
import re
from dataclasses import dataclass

from loguru import logger
from openai import APIConnectionError, APIStatusError, OpenAI

from src.ai.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from src.utils.config import Settings, load_examples, load_profile
from src.utils.errors import AIFatalError


@dataclass
class GeneratedProposal:
    content: str
    amount_brl: float
    delivery_time: str
    hours_estimate: float | None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# ── Parâmetros da chamada ao DeepSeek ──────────────────────────────────────────
# DeepSeek é OpenAI-compatible: usamos o SDK `openai` apontado pro base_url dele.
# response_format=json_object garante a ESTRUTURA do retorno independente da
# temperatura, então dá pra usar uma temp moderada p/ variar o texto (evitar
# clichê de IA) sem arriscar o JSON. Escala DeepSeek: 0.0 determinístico,
# 1.0 equilibrado, 1.3 conversa, 1.5 criativo. Ajuste aqui se quiser.
_TEMPERATURE = 1.0
# Teto de saída. O default do DeepSeek é baixo e pode TRUNCAR o JSON → fixe alto.
_MAX_TOKENS = 8192
# Retries automáticos do SDK p/ erros transitórios (conexão, 429, 5xx) com backoff
# e respeito ao Retry-After. Timeout alto porque, sob carga, o DeepSeek segura a
# conexão aberta enquanto enfileira (keep-alive) em vez de devolver 503 na hora —
# é justamente por isso que ele sofre menos com indisponibilidade que o Gemini.
_MAX_RETRIES = 5
_TIMEOUT_SECONDS = 600.0

# HTTP que NÃO adianta repetir → aborta a run (vira AIFatalError):
#   401 chave inválida · 402 saldo insuficiente · 403 sem permissão.
_FATAL_STATUS = {401, 402, 403}
# HTTP transitório: o SDK já re-tentou _MAX_RETRIES vezes; se ainda chegou aqui,
# não adianta seguir nesta run → também vira AIFatalError (salva o progresso e para).
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _client(settings: Settings) -> OpenAI:
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        max_retries=_MAX_RETRIES,
        timeout=_TIMEOUT_SECONDS,
    )


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


def _create_completion(client: OpenAI, settings: Settings, system: str, user_prompt: str):
    """Chama o chat completion do DeepSeek e CLASSIFICA o erro final.

    O SDK já re-tenta sozinho os erros transitórios (conexão, 429, 5xx) _MAX_RETRIES
    vezes com backoff. O que chega às exceções aqui é o resultado FINAL:
      - 401/402/403 → AIFatalError (aborta a run: chave/saldo/permissão).
      - 429/5xx/conexão que sobreviveram aos retries → AIFatalError (não adianta
        seguir agora; o caller salva o progresso e para).
      - 400/422/404 e demais → propaga como erro POR-VAGA (o caller pula a vaga).
    """
    try:
        return client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
            stream=False,
        )
    except APIConnectionError as e:
        # rede/timeout (sem status_code) esgotou os retries do SDK → não adianta seguir
        raise AIFatalError(f"DeepSeek inacessível (rede/timeout): {e}") from e
    except APIStatusError as e:
        status = getattr(e, "status_code", None)
        if status in _FATAL_STATUS:
            raise AIFatalError(
                f"Erro fatal da API DeepSeek (HTTP {status} — chave/saldo/permissão): {e}"
            ) from e
        if status in _RETRYABLE_STATUS:
            raise AIFatalError(
                f"DeepSeek indisponível após {_MAX_RETRIES} tentativas (HTTP {status}): {e}"
            ) from e
        raise  # 400/422/404 etc.: request por-vaga inválido → pula a vaga, não aborta


def generate(settings: Settings, job: dict, insight: dict | None) -> GeneratedProposal:
    if not settings.deepseek_api_key:
        raise AIFatalError(
            "DEEPSEEK_API_KEY não configurada no .env — não dá pra gerar propostas."
        )

    profile = load_profile()
    examples = load_examples()
    system = _build_system(profile, examples)
    discount = float(profile.get("bid_discount_pct", 0.10))

    client = _client(settings)
    user_prompt = build_user_prompt(job, insight, discount)
    logger.debug("Prompt user ({} chars): {}", len(user_prompt), user_prompt[:200])

    resp = _create_completion(client, settings, system, user_prompt)

    raw = (resp.choices[0].message.content if resp.choices else None) or ""
    if not raw.strip():
        # resposta vazia/bloqueada → por-vaga (pula), não é fatal
        raise ValueError("DeepSeek retornou resposta vazia")
    match = _JSON_RE.search(raw)
    data = json.loads(match.group(0) if match else raw)

    amount_brl = float(data["amount_brl"])
    avg = (insight or {}).get("avg_bid_value")
    if avg:
        target = round(float(avg) * (1 - discount))
        if abs(target - amount_brl) > 0.5:
            logger.info(
                "Override amount_brl: IA={} → target={} (avg={} desc={:.0%})",
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
