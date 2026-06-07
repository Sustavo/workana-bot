import json
import re
from dataclasses import dataclass

import google.generativeai as genai
from loguru import logger

from src.ai.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from src.utils.config import Settings, load_examples, load_profile


@dataclass
class GeneratedProposal:
    content: str
    amount_brl: float
    delivery_time: str
    hours_estimate: float | None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


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
    genai.configure(api_key=settings.google_api_key)
    profile = load_profile()
    examples = load_examples()
    system = _build_system(profile, examples)
    discount = float(profile.get("bid_discount_pct", 0.10))

    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=system,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.6,
        },
    )
    user_prompt = build_user_prompt(job, insight, discount)
    logger.debug("Prompt user ({} chars): {}", len(user_prompt), user_prompt[:200])
    resp = model.generate_content(user_prompt)
    raw = resp.text or ""
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
