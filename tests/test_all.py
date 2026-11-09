"""python -m pytest tests  (ya da: python tests/test_all.py)"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bs4 import BeautifulSoup  # noqa: E402

from evbul.core import matches  # noqa: E402
from evbul.db import DB  # noqa: E402
from evbul.models import Listing, guess_type, parse_price, split_postcode_city  # noqa: E402
from evbul.sources.funda import Funda  # noqa: E402
from evbul.sources.generic import Generic  # noqa: E402
from evbul.sources.pararius import Pararius  # noqa: E402

PARARIUS = """
<section class="listing-search-item">
 <div class="listing-search-item__depiction"><img src="https://img/p1.jpg"></div>
 <h2><a class="listing-search-item__link--title" href="/apartment-for-rent/amsterdam/abc/prinsengracht">Apartment Prinsengracht 123</a></h2>
 <div class="listing-search-item__sub-title">1015 AB Amsterdam (Jordaan)</div>
 <div class="listing-search-item__price">€1,750 per month</div>
 <ul><li class="illustrated-features__item--surface-area">55 m²</li>
     <li class="illustrated-features__item--number-of-rooms">2 rooms</li>
     <li class="illustrated-features__item--interior">Furnished</li></ul>
</section>
<section class="listing-search-item">
 <h2><a class="listing-search-item__link--title" href="/room-for-rent/amsterdam/x/kinkerstraat">Room Kinkerstraat 9</a></h2>
 <div class="listing-search-item__sub-title">1053 DT Amsterdam</div>
 <div class="listing-search-item__price">€850 per month</div>
 <ul><li class="illustrated-features__item--surface-area">14 m²</li></ul>
</section>"""

FUNDA = """
<div><div><a href="/detail/huur/amsterdam/appartement-prinsengracht-123/43000001/">Prinsengracht 123</a></div>
<p>1015 AB Amsterdam</p><p>€ 1.760 /maand</p><ul><li>56 m²</li><li>2 kamers</li></ul></div>
<div><div><a href="/detail/huur/utrecht/studio-oudegracht-5/43000002/">Oudegracht 5</a></div>
<p>3511 AA Utrecht</p><p>€ 1.100 /maand</p><ul><li>30 m²</li></ul></div>"""

GENERIC = """
<div class="grid"><div class="item"><a href="/en/housing-offer/studio-utrecht-biltstraat/">
<h3>Studio Biltstraat 40</h3></a><span>Utrecht</span><span>€ 1.150,- p/m</span><span>32 m²</span></div>
<div class="item"><a href="/en/housing-offer/apartment-breda-x/"><h3>Apartment Breda</h3></a>
<span>Breda</span><span>€ 1.400</span></div></div>"""


def test_helpers():
    assert parse_price("€ 1.250 per maand") == 1250
    assert parse_price("€1,750 per month") == 1750
    assert parse_price("€ 1.150,- p/m") == 1150
    assert parse_price("1250.00") == 1250
    assert guess_type("Kamer Kinkerstraat") == "room"
    assert guess_type("2-kamer appartement") == "apartment"
    assert guess_type("Studio Oudegracht") == "studio"
    assert guess_type("Eengezinswoning Lindelaan") == "house"
    assert split_postcode_city("1015 AB Amsterdam (Jordaan)") == ("1015 AB", "Amsterdam")


def test_pararius():
    soup = BeautifulSoup(PARARIUS, "html.parser")
    ls = Pararius().parse(soup.select("section.listing-search-item"), "Amsterdam")
    assert len(ls) == 2
    a, r = ls
    assert (a.price, a.area_m2, a.rooms, a.type, a.furnished, a.postcode) == (1750, 55, 2, "apartment", "furnished", "1015 AB")
    assert a.url.startswith("https://www.pararius.com/")
    assert (r.type, r.price) == ("room", 850)


def test_funda():
    ls = Funda().parse(BeautifulSoup(FUNDA, "html.parser"), "Amsterdam")
    assert len(ls) == 2
    assert (ls[0].price, ls[0].area_m2, ls[0].rooms, ls[0].type) == (1760, 56, 2, "apartment")
    assert ls[1].type == "studio"


def test_generic():
    g = Generic("househunting", {"link_pattern": "/en/housing-offer/[^/?#]+/?$", "strict_city": True})
    ls = g.parse(BeautifulSoup(GENERIC, "html.parser"), "https://househunting.nl/en/housing-offer/", "Utrecht")
    assert len(ls) == 1
    assert (ls[0].title, ls[0].price, ls[0].area_m2, ls[0].type) == ("Studio Biltstraat 40", 1150, 32, "studio")


def test_db_dedupe_and_query():
    with tempfile.TemporaryDirectory() as d:
        db = DB(os.path.join(d, "t.db"))
        p = Listing("pararius", "https://p/1", "Apartment Prinsengracht 123", price=1750, city="Amsterdam", area_m2=55)
        f = Listing("funda", "https://f/1", "Prinsengracht 123", price=1760, city="Amsterdam", area_m2=56, type="apartment")
        s = Listing("funda", "https://f/2", "Studio Oudegracht 5", price=1100, city="Utrecht", area_m2=30)
        assert db.upsert(p) is True
        assert db.upsert(f) is False         # aynı ev, başka site → yeni sayılmaz
        assert db.upsert(p) is False         # tekrar görüldü
        assert db.upsert(s) is True
        rows = db.query()
        assert len(rows) == 2
        top = [r for r in rows if r["source"] == "pararius"][0]
        assert top["also_on"] == [{"source": "funda", "url": "https://f/1"}]
        assert [r["title"] for r in db.query(types=["studio"])] == ["Studio Oudegracht 5"]
        assert len(db.query(max_price=1200)) == 1
        assert len(db.query(cities=["amsterdam"])) == 1
        db.set_flag(s.uid, "hidden", 1)
        assert len(db.query()) == 1


def test_matches():
    f = {"types": ["studio", "apartment"], "max_price": 1500, "min_area": 25, "exclude_words": ["anti-kraak"]}
    assert matches(Listing("x", "u", "Studio A", price=1200, area_m2=30), f)
    assert not matches(Listing("x", "u", "Kamer A", price=600), f)
    assert not matches(Listing("x", "u", "Studio A", price=1800), f)
    assert not matches(Listing("x", "u", "Anti-kraak studio", price=500), f)
    assert matches(Listing("x", "u", "Studio A"), f)   # bilinmeyen fiyat elenmez


def test_block_detection():
    from evbul.sources.base import looks_blocked
    assert looks_blocked("<html><head><title>Just a moment...</title></head></html>")
    assert looks_blocked("<title>Je bent bijna op de pagina die je zoekt [funda]</title>")
    assert not looks_blocked("<title>Huurwoningen Amsterdam [funda]</title><script>captcha</script>")


def test_run_once_with_fake_fetcher():
    from evbul.core import run_once

    class Fake:
        def html(self, url):
            return PARARIUS if "pararius" in url else "<html></html>"

        def post_json(self, *a, **k):
            return {"data": {"products": {"items": []}}}

    with tempfile.TemporaryDirectory() as d:
        db = DB(os.path.join(d, "t.db"))
        cfg = {"cities": ["Amsterdam"], "max_pages": 1, "filters": {"max_price": 1000},
               "sources": {"pararius": {}, "holland2stay": {}}}
        r = run_once(cfg, db, fetcher=Fake())
        assert r["counts"]["pararius"] == 2
        assert [l["title"] for l in r["new"]] == ["Room Kinkerstraat 9"]   # 1750'lik filtreye takıldı


def test_extract_and_details_pipeline():
    from datetime import date
    from evbul.core import fetch_details, matches
    from evbul.detail import extract_detail
    from evbul.extract import rule_extract
    r = rule_extract("Beschikbaarheid Vanaf 01-12-2026. Huurperiode minimaal 12 maanden.", date(2026, 11, 9))
    assert (r["available_from"], r["min_months"], r["stay"]) == ("2026-12-01", 12, "long")
    page = ("<html><head><meta name='description' content='kort'></head><body><nav>menu</nav>"
            "<div class='object-description'><p>Lovely furnished studio near the centre. " + "x " * 80 +
            "</p><p>Available from 1 February 2027, maximum 6 months (short stay).</p></div>"
            "<footer>©</footer></body></html>")
    desc, text = extract_detail(page)
    assert desc.startswith("Lovely furnished studio") and "menu" not in text

    class Fake:
        def html(self, url):
            return page

    with tempfile.TemporaryDirectory() as d:
        db = DB(os.path.join(d, "t.db"))
        l = Listing("kamernet", "https://k/1", "Studio Test", price=900, city="Eindhoven")
        db.upsert(l)
        assert fetch_details({}, db, Fake()) == 1
        row = db.get(l.uid)
        assert (row["available_from"], row["max_months"], row["stay"]) == ("2027-02-01", 6, "short")
        assert row["description"].startswith("Lovely")
        assert db.needs_details() == []
        # kart tahmini detay sonucunu ezmemeli
        db.upsert(Listing("kamernet", "https://k/1", "Studio Test", price=900, city="Eindhoven", stay="long"))
        assert db.get(l.uid)["stay"] == "short"
        assert len(db.query(stay=["long"], known_only=True)) == 0
        assert len(db.query(stay=["short"])) == 1
        assert len(db.query(available_by="2027-01-01", known_only=True)) == 0
        assert len(db.query(available_by="2027-03-01")) == 1
        assert not matches(row, {"stay": ["long"]})
        assert matches(row, {"stay": ["short"], "available_by": "2027-02-01"})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("✓", name)
