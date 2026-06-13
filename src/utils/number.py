"""Parser de valores monetários robusto pra formato BR e US.

O Workana mistura formatos: o 'Lance mínimo' aparece em US (`R$ 780.00`) enquanto
orçamentos costumam vir em BR (`R$ 7.331,00`). Os parsers antigos assumiam só BR
(`.replace(".", "").replace(",", ".")`), o que transformava `780.00` em `78000` —
uma das causas do "valor errado". Esta função centraliza a lógica.

Heurística:
- Se houver vírgula E ponto, o separador que vier por ÚLTIMO é o decimal.
- Só vírgula → decimal (BR): `1.234,5` cai no caso acima; `160,5` → 160.5.
- Só ponto → é decimal, EXCETO quando parece milhar BR (`7.331`: um único ponto,
  exatamente 3 dígitos depois e parte inteira de até 3 dígitos).
"""
from __future__ import annotations

import re

# Captura o primeiro "número" plausível (dígitos com . e , no meio).
_NUM_TOKEN = re.compile(r"\d[\d.,]*\d|\d")


def parse_money(text: str | None) -> float | None:
    """Parseia o primeiro valor monetário do texto. Retorna float ou None.

    Exemplos:
        '7.331,00' (BR)        -> 7331.0
        '7331.00'  (US)        -> 7331.0
        'R$ 780.00' (US 2 casas) -> 780.0
        '7.331'    (milhar BR) -> 7331.0
        '1,234.56' (US milhar) -> 1234.56
        '160'                  -> 160.0
        '1.234,5'              -> 1234.5
    """
    if not text:
        return None
    m = _NUM_TOKEN.search(str(text))
    if not m:
        return None
    s = m.group(0)
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):   # BR: 7.331,00 → vírgula é o decimal
            s = s.replace(".", "").replace(",", ".")
        else:                              # US: 1,234.56 → ponto é o decimal
            s = s.replace(",", "")
    elif has_comma:
        # uma vírgula = decimal BR; várias vírgulas (1,234,567) = separador de milhar US
        if s.count(",") > 1:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        tail = s.rsplit(".", 1)[1]
        head = s.split(".", 1)[0]
        # milhar BR: um único ponto, 3 dígitos no fim e parte inteira curta (<=3)
        if s.count(".") == 1 and len(tail) == 3 and len(head) <= 3:
            s = s.replace(".", "")
        elif s.count(".") > 1:
            # 1.234.567 → todos os pontos são milhar
            s = s.replace(".", "")
        # senão: ponto é o decimal (780.00) — não mexe

    try:
        return float(s)
    except ValueError:
        return None


def parse_money_max(text: str | None) -> float | None:
    """Maior valor entre todos os tokens do texto.
    Útil pra faixas tipo 'R$ 500 - R$ 1.000' (retorna 1000.0 = o teto)."""
    if not text:
        return None
    vals: list[float] = []
    for tok in re.findall(r"\d[\d.,]*\d|\d", str(text)):
        v = parse_money(tok)
        if v is not None:
            vals.append(v)
    return max(vals) if vals else None


def parse_int(text: str | None) -> int | None:
    """Primeiro inteiro do texto (ex.: 'Propostas: 25' → 25)."""
    if not text:
        return None
    m = re.search(r"\d+", str(text))
    return int(m.group(0)) if m else None
