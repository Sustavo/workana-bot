import re
from dataclasses import dataclass

from loguru import logger
from playwright.sync_api import Page


@dataclass
class ConnectionsStatus:
    available: int | None
    used: int | None
    raw: str


def scrape_connections(page: Page, user_id: str) -> ConnectionsStatus:
    url = f"https://www.workana.com/freelancer/{user_id}"
    page.goto(url, wait_until="domcontentloaded")
    el = page.query_selector("span.max-number-of-available-skills")
    raw = (el.inner_text().strip() if el else "")
    nums = re.findall(r"\d+", raw)
    available = int(nums[0]) if nums else None
    used = int(nums[1]) if len(nums) > 1 else None
    logger.info("Conexões: {} (raw='{}')", f"{available}/{used}" if available else "??", raw)
    return ConnectionsStatus(available=available, used=used, raw=raw)
