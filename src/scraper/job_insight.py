import re
from dataclasses import dataclass

from loguru import logger
from playwright.sync_api import Page


@dataclass
class JobInsight:
    avg_bid_text: str
    avg_bid_value: float | None
    competitor_count: int | None
    raw_dump: str


_NUM_RE = re.compile(r"([\d\.]+,\d{2}|\d[\d\.]+|\d+)")


def _parse_number(text: str) -> float | None:
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    s = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def scrape(page: Page, job_slug: str) -> JobInsight:
    url = f"https://www.workana.com/job/insight/{job_slug}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=10_000)

    body_text = page.inner_text("body")[:4000]
    avg_bid_value: float | None = None
    avg_bid_text = ""
    competitor_count: int | None = None

    for line in body_text.splitlines():
        low = line.lower()
        if "orçamento médio" in low or "média" in low:
            avg_bid_text = line.strip()
            avg_bid_value = _parse_number(line)
        if "concorrentes" in low or "freelancers" in low:
            num = _parse_number(line)
            if num is not None:
                competitor_count = int(num)

    insight = JobInsight(
        avg_bid_text=avg_bid_text,
        avg_bid_value=avg_bid_value,
        competitor_count=competitor_count,
        raw_dump=body_text,
    )
    logger.info("Insight {}: média={} concorrentes={}", job_slug, avg_bid_value, competitor_count)
    return insight
