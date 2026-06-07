"""Debug ad-hoc da página de insight: abre browser, vai pra URL, scrolla, screenshot, dump.
Uso: python debug_insight.py <slug>
"""
import sys
import time
from pathlib import Path

from src.browser.session import ensure_logged_in, open_context
from src.utils.config import Settings


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python debug_insight.py <slug>")
        return 1
    slug = sys.argv[1]
    settings = Settings.load()
    out_dir = Path("data/insights/debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    with open_context(settings) as ctx:
        ensure_logged_in(ctx, settings.workana_jobs_url)
        page = ctx.pages[0]
        url = f"https://www.workana.com/job/insight/{slug}"
        print(f"→ {url}")
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            print(f"networkidle timeout: {e}")

        for i in range(5):
            page.mouse.wheel(0, 1500)
            time.sleep(1.0)

        time.sleep(3)

        body = page.inner_text("body")
        html = page.content()
        (out_dir / f"{slug}.txt").write_text(body, encoding="utf-8")
        (out_dir / f"{slug}.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{slug}.png"), full_page=True)
        print(f"✓ Dumped to {out_dir}/{slug}.{{txt,html,png}}")

        rs = [l for l in body.splitlines() if "R$" in l or "valor médio" in l.lower() or "orçamento médio" in l.lower() or "média" in l.lower()]
        print("\n--- linhas relevantes ---")
        for l in rs[:30]:
            print(f"  {l!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
