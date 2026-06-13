import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from playwright.sync_api import Page

from src.utils.number import parse_money

ROOT = Path(__file__).resolve().parents[2]
INSIGHTS_DUMP_DIR = ROOT / "data" / "insights"


@dataclass
class JobInsight:
    avg_bid_text: str
    avg_bid_value: float | None
    raw_dump: str


_NUM_RE = re.compile(r"([\d\.]+,\d{2}|\d[\d\.]+|\d+)")
_CCY = r"(?:BRL|R\$|USD|US\$|\$)"
_AVG_RE_VALUE_FIRST = re.compile(
    rf"{_CCY}\s*([\d\.\,]+)\s*\n?\s*(?:or[çc]amento m[ée]dio|valor m[ée]dio)",
    re.IGNORECASE | re.DOTALL,
)
_AVG_RE_LABEL_FIRST = re.compile(
    rf"(?:valor m[ée]dio|or[çc]amento m[ée]dio).{{0,80}}?{_CCY}\s*([\d\.\,]+)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_number(text: str) -> float | None:
    # Delegado pro parser central, que entende BR (7.331,00) E US (780.00).
    # O parser antigo (replace(".","").replace(",",".")) transformava 780.00 em 78000.
    return parse_money(text)


def _dump_html(page: Page, job_slug: str) -> Path:
    INSIGHTS_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    path = INSIGHTS_DUMP_DIR / f"{job_slug}.html"
    try:
        path.write_text(page.content(), encoding="utf-8")
    except Exception as e:
        logger.warning("Falha salvando dump de insight pra {}: {}", job_slug, e)
    return path


def scrape(page: Page, job_slug: str) -> JobInsight:
    url = f"https://www.workana.com/job/insight/{job_slug}"
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(
            "text=/valor m[ée]dio|or[çc]amento m[ée]dio/i", timeout=4_000
        )
    except Exception:
        logger.debug("Seletor de média não apareceu em {} (pode não estar no plano)", job_slug)

    body_text = page.inner_text("body")
    avg_bid_value: float | None = None
    avg_bid_text = ""

    for regex in (_AVG_RE_VALUE_FIRST, _AVG_RE_LABEL_FIRST):
        m = regex.search(body_text)
        if m:
            avg_bid_text = m.group(0).strip()
            avg_bid_value = _parse_number(m.group(1))
            if avg_bid_value:
                break

    if avg_bid_value is None:
        lines = body_text.splitlines()
        for i, line in enumerate(lines):
            low = line.lower().strip()
            if low in ("orçamento médio", "valor médio", "valor médio das propostas"):
                for j in (i - 1, i - 2, i + 1, i + 2):
                    if 0 <= j < len(lines):
                        v = _parse_number(lines[j])
                        if v:
                            avg_bid_text = f"{lines[j].strip()} (label: {line.strip()})"
                            avg_bid_value = v
                            break
                if avg_bid_value:
                    break

    if avg_bid_value is None:
        dump = _dump_html(page, job_slug)
        logger.warning(
            "Insight {} sem média; HTML salvo em {} pra debug", job_slug, dump
        )

    insight = JobInsight(
        avg_bid_text=avg_bid_text,
        avg_bid_value=avg_bid_value,
        raw_dump=body_text[:4000],
    )
    logger.info("Insight {}: média={}", job_slug, avg_bid_value)
    return insight
