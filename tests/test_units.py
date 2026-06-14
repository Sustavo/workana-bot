"""Testes de unidade (sem browser): parsing de número, filtros e presets de velocidade."""
from types import SimpleNamespace

from src.filters.matcher import _cat_match, passes, passes_detail
from src.scraper.jobs_list import JobCard, feed_exhausted
from src.utils.config import Settings
from src.utils.number import parse_int, parse_money, parse_money_max


def _card(slug="s", title="React app", skills=None, bids="Propostas: 3",
          bids_count=3, budget_value=None, budget_text="", has_open_bid=True,
          is_featured=False):
    return JobCard(
        slug=slug, title=title, url="u", action_text="Fazer uma proposta",
        has_open_bid=has_open_bid, budget_text=budget_text, skills=skills or ["React"],
        bids_text=bids, date_text="hoje", bids_count=bids_count, budget_value=budget_value,
        is_featured=is_featured,
    )


# ── parse_money ────────────────────────────────────────────────────────────
def test_parse_money_formats():
    assert parse_money("R$ 780.00") == 780.0      # US, 2 casas (caso 'Lance mínimo' Workana)
    assert parse_money("7.331,00") == 7331.0       # BR
    assert parse_money("7331.00") == 7331.0        # US
    assert parse_money("7.331") == 7331.0          # milhar BR
    assert parse_money("1,234.56") == 1234.56      # US milhar
    assert parse_money("1.234,5") == 1234.5        # BR
    assert parse_money("160") == 160.0
    assert parse_money("R$ 1.500") == 1500.0
    assert parse_money("") is None
    assert parse_money(None) is None


def test_parse_money_max_and_int():
    assert parse_money_max("R$ 500 - R$ 1.000") == 1000.0
    assert parse_money_max("R$ 1.200,00 a R$ 3.000,00") == 3000.0
    assert parse_int("Propostas: 25") == 25
    assert parse_int("sem numero") is None


# ── matcher.passes (card) ──────────────────────────────────────────────────
FILTERS = {
    "blocked_keywords": ["wordpress"],
    "required_keywords_any": [],
    "allowed_categories": [],
    "blocked_categories": ["Suporte Administrativo", "Marketing e Vendas"],
    "min_budget_usd": 300,
    "max_competing_proposals": 25,
}
PROFILE = {"do_not_take": []}


def test_passes_ok():
    assert passes(_card(), FILTERS, PROFILE) == (True, "")


def test_passes_blocked_keyword():
    ok, reason = passes(_card(title="Site WordPress", skills=["WordPress"]), FILTERS, PROFILE)
    assert not ok and "wordpress" in reason


def test_passes_saturated():
    ok, reason = passes(_card(bids_count=40), FILTERS, PROFILE)
    assert not ok and "saturada" in reason


def test_passes_cheap_budget_on_card():
    ok, reason = passes(_card(budget_value=100.0), FILTERS, PROFILE)
    assert not ok and "orçamento" in reason


def test_passes_no_open_bid():
    ok, reason = passes(_card(has_open_bid=False), FILTERS, PROFILE)
    assert not ok


# ── matcher.passes_detail ──────────────────────────────────────────────────
def test_detail_category_order_insensitive():
    # site mostra "Marketing e Vendas"; filtro tem "Marketing e Vendas" → bloqueia
    d = SimpleNamespace(category="Marketing e Vendas", budget_text="R$ 2.000")
    ok, reason = passes_detail(d, FILTERS, PROFILE)
    assert not ok and "categoria" in reason


def test_detail_ok_category():
    d = SimpleNamespace(category="TI e Programação", budget_text="R$ 1.500")
    assert passes_detail(d, FILTERS, PROFILE) == (True, "")


def test_detail_cheap_budget():
    d = SimpleNamespace(category="TI e Programação", budget_text="R$ 150")
    ok, reason = passes_detail(d, FILTERS, PROFILE)
    assert not ok and "orçamento" in reason


def test_cat_match():
    assert _cat_match("Vendas e Marketing", "Marketing e Vendas")
    assert _cat_match("Design", "Design & Multimedia")
    assert not _cat_match("TI e Programação", "Marketing e Vendas")


# ── feed_exhausted (parar no fim dos resultados reais) ─────────────────────
def test_feed_continua_pagina_mista():
    cards = [_card(slug="a", is_featured=True), _card(slug="b", is_featured=False)]
    assert feed_exhausted(cards, set()) is None


def test_feed_para_so_patrocinadas():
    cards = [_card(slug="a", is_featured=True), _card(slug="b", is_featured=True)]
    r = feed_exhausted(cards, set())
    assert r and "patrocinad" in r


def test_feed_para_so_repetidas():
    cards = [_card(slug="a"), _card(slug="b")]
    r = feed_exhausted(cards, {"a", "b"})
    assert r and "repete" in r


def test_feed_para_pagina_vazia():
    r = feed_exhausted([], {"a"})
    assert r and "sem cards" in r


def test_feed_continua_pagina_nova_com_seen():
    # página com vagas inéditas (não-featured) mesmo já tendo visto outras → continua
    cards = [_card(slug="novo1"), _card(slug="novo2")]
    assert feed_exhausted(cards, {"velho"}) is None


# ── Settings presets de velocidade ─────────────────────────────────────────
def test_speed_presets():
    cons = Settings.load(speed_override="conservador")
    rap = Settings.load(speed_override="rapido")
    assert cons.min_delay_seconds >= rap.min_delay_seconds
    assert cons.max_actions_per_hour == 40
    assert rap.long_pause_chance == 0.0
    # default cai em equilibrado
    assert Settings.load(speed_override="invalido").speed_profile == "equilibrado"


# ── tracker: dedup (drafts já salvos) + summary ────────────────────────────
def test_tracker_all_draft_slugs_and_summary():
    import tempfile
    from pathlib import Path

    from src.db.tracker import Tracker

    db = Path(tempfile.mkdtemp()) / "t.db"
    t = Tracker(db)
    try:
        t.upsert_job("a", "A", "ua", "drafted")
        t.save_draft("a", {"x": 1})
        t.upsert_job("b", "B", "ub", "drafted")
        t.save_draft("b", {"x": 2})
        t.mark_draft("b", "sent")
        assert t.all_draft_slugs() == {"a", "b"}
        s = t.summary()
        assert s["drafts"].get("pending") == 1
        assert s["drafts"].get("sent") == 1
        assert s["jobs"].get("drafted") == 2
    finally:
        t.close()


# ── approve.py: parsing das flags --all / --yes / --speed ──────────────────
def test_approve_parse_args():
    import approve
    a = approve._parse_args(["--all"])
    assert a.all and not a.yes and a.speed is None
    a = approve._parse_args(["--all", "--yes", "--speed", "conservador"])
    assert a.all and a.yes and a.speed == "conservador"
    a = approve._parse_args(["-a", "-y"])
    assert a.all and a.yes
    a = approve._parse_args([])
    assert not a.all and not a.yes and a.speed is None


if __name__ == "__main__":
    # Runner simples caso pytest não esteja instalado.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
