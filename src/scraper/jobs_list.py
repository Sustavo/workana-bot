from dataclasses import dataclass
from urllib.parse import urljoin

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.utils.number import parse_int, parse_money_max


@dataclass
class JobCard:
    slug: str
    title: str
    url: str
    action_text: str          # "Fazer uma proposta" | "Ir para as mensagens"
    has_open_bid: bool        # True só quando ainda dá pra propor
    budget_text: str
    skills: list[str]
    bids_text: str            # ex: "Propostas: 3"
    date_text: str            # ex: "Publicado: 5 minutos"
    bids_count: int | None = None     # parseado de bids_text
    budget_value: float | None = None  # teto do orçamento (quando aparece no card)


def _slug_from_url(url: str) -> str:
    # https://www.workana.com/job/<slug> → <slug>
    parts = url.rstrip("/").split("/job/")
    return parts[-1] if len(parts) == 2 else url


def scrape_page(page: Page) -> list[JobCard]:
    try:
        page.wait_for_selector(".project-item", timeout=8_000)
    except PWTimeout:
        logger.info("Sem .project-item em {} — fim do feed", page.url)
        return []
    cards = page.query_selector_all(".project-item.js-project, .project-item")
    out: list[JobCard] = []
    for c in cards:
        title_a = c.query_selector(".project-title a")
        if not title_a:
            continue
        title = (title_a.inner_text() or "").strip()
        href = title_a.get_attribute("href") or ""
        url = urljoin(page.url, href)
        slug = _slug_from_url(url)

        btn = c.query_selector(".project-actions a.btn, .btn-group a.btn")
        action_text = (btn.inner_text().strip() if btn else "").lower()
        has_open_bid = "fazer uma proposta" in action_text

        budget_el = c.query_selector(".budget")
        skills_els = c.query_selector_all(".skills a.skill, .skills .skill")
        bids_el = c.query_selector(".bids")
        date_el = c.query_selector(".date")

        budget_text = budget_el.inner_text().strip() if budget_el else ""
        bids_text = bids_el.inner_text().strip() if bids_el else ""
        out.append(JobCard(
            slug=slug,
            title=title,
            url=url,
            action_text=btn.inner_text().strip() if btn else "",
            has_open_bid=has_open_bid,
            budget_text=budget_text,
            skills=[s.inner_text().strip() for s in skills_els],
            bids_text=bids_text,
            date_text=(date_el.inner_text().strip() if date_el else ""),
            bids_count=parse_int(bids_text),
            budget_value=parse_money_max(budget_text),
        ))
    logger.info("Coletados {} cards na página {}", len(out), page.url)
    return out


def has_next_page(page: Page) -> bool:
    next_link = page.query_selector("ul.pagination a[rel='next'], ul.pagination li.next a")
    return next_link is not None


def go_to_next_page(page: Page) -> bool:
    next_link = page.query_selector("ul.pagination a[rel='next'], ul.pagination li.next a")
    if not next_link:
        return False
    href = next_link.get_attribute("href")
    if not href:
        return False
    page.goto(urljoin(page.url, href), wait_until="domcontentloaded")
    return True
