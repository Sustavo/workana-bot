import re
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parents[2]
INSIGHTS_DUMP_DIR = ROOT / "data" / "insights"


@dataclass
class JobInsight:
    avg_bid_text: str
    avg_bid_value: float | None
    competitor_count: int | None
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
_COUNT_RE = re.compile(r"(\d+)\s+(propostas|concorrentes|freelancers)", re.IGNORECASE)


def _parse_number(text: str) -> float | None:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    s = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


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
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    try:
        page.wait_for_selector(
            "text=/valor m[ée]dio|or[çc]amento m[ée]dio/i", timeout=15_000
        )
    except Exception:
        logger.debug("Seletor de média não apareceu em {} (pode não estar no plano)", job_slug)

    try:
        page.mouse.wheel(0, 2000)
        time.sleep(0.6)
    except Exception:
        pass

    body_text = page.inner_text("body")
    avg_bid_value: float | None = None
    avg_bid_text = ""
    competitor_count: int | None = None

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

    mc = _COUNT_RE.search(body_text)
    if mc:
        try:
            competitor_count = int(mc.group(1))
        except ValueError:
            competitor_count = None
    if competitor_count is None:
        for line in body_text.splitlines():
            low = line.lower()
            if "concorrentes" in low or "freelancers" in low or "propostas" in low:
                num = _parse_number(line)
                if num is not None:
                    competitor_count = int(num)
                    break

    if avg_bid_value is None:
        dump = _dump_html(page, job_slug)
        logger.warning(
            "Insight {} sem média; HTML salvo em {} pra debug", job_slug, dump
        )

    insight = JobInsight(
        avg_bid_text=avg_bid_text,
        avg_bid_value=avg_bid_value,
        competitor_count=competitor_count,
        raw_dump=body_text[:4000],
    )
    logger.info(
        "Insight {}: média={} concorrentes={}",
        job_slug,
        avg_bid_value,
        competitor_count,
    )
    return insight
