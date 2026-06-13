from dataclasses import dataclass
from urllib.parse import urljoin

from loguru import logger
from playwright.sync_api import Page


@dataclass
class JobDetail:
    slug: str
    url: str
    title: str
    description: str
    budget_text: str
    skills: list[str]
    bid_href: str             # /messages/bid/<slug>
    bid_button_visible: bool
    proposals_status: str     # ex.: "Analisando propostas"
    client_country: str
    category: str = ""        # ex.: "TI e Programação" (do breadcrumb)


def scrape(page: Page, url: str) -> JobDetail:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("h1.title, h1.h3.title", timeout=15_000)

    title_el = page.query_selector("h1.title, h1.h3.title")
    desc_el = page.query_selector("div.expander[data-text-expand], div.expander")
    budget_el = page.query_selector("h4.budget, .budget")
    skills_els = page.query_selector_all("div.skills a.skill, .skills .skill")
    bid_btn = page.query_selector("a#bid_button")
    status_el = page.query_selector("span.pry.label.rounded, .label.rounded")
    country_el = page.query_selector("span.country")

    # Categoria: último link de categoria no breadcrumb (o mais específico).
    category = ""
    cat_links = page.query_selector_all(".breadcrumb a[href*='category=']")
    if cat_links:
        category = (cat_links[-1].inner_text() or "").strip()

    slug = url.rstrip("/").split("/job/")[-1]
    bid_href = ""
    if bid_btn:
        bid_href = bid_btn.get_attribute("href") or ""
        bid_href = urljoin(url, bid_href)

    detail = JobDetail(
        slug=slug,
        url=url,
        title=(title_el.inner_text().strip() if title_el else ""),
        description=(desc_el.inner_text().strip() if desc_el else ""),
        budget_text=(budget_el.inner_text().strip() if budget_el else ""),
        skills=[s.inner_text().strip() for s in skills_els],
        bid_href=bid_href,
        bid_button_visible=bid_btn is not None,
        proposals_status=(status_el.inner_text().strip() if status_el else ""),
        client_country=(country_el.inner_text().strip() if country_el else ""),
        category=category,
    )
    logger.info("Detalhe coletado: {} (bid_btn={})", detail.title[:50], detail.bid_button_visible)
    return detail
