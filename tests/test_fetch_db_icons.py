"""HTML parsing of cookierundb list pages (tools/fetch_db_icons.py)."""
from tools.fetch_db_icons import parse_list_page

SAMPLE = """
<a class="ecard" href="../cookies/ch40" style="--accent: var(--grade-l)" data-name="Tiger Lily Cookie" data-grade="L">
  <span class="icon-frame"><img src="../assets/icons/cookies/ch40.png" alt="" loading="lazy"></span>
  <span class="e-name">Tiger Lily Cookie</span><span class="e-sub">ขว้างหอก</span><span class="badge grade grade-L">L</span>
</a><a class="ecard" href="../cookies/ch85" style="--accent: var(--grade-ss)" data-name="Admiral Gimbap Cookie" data-grade="SS">
  <span class="icon-frame"><img src="../assets/icons/cookies/ch85.png" alt="" loading="lazy"></span>
  <span class="e-name">Admiral Gimbap Cookie</span><span class="e-sub">Admiral&#x27;s Charge</span><span class="badge grade grade-SS">S+</span>
</a><a class="ecard" href="../pets/pet53" data-name="Furball Pup" data-grade="A">
  <span class="icon-frame"><img src="../assets/icons/pets/pet53.png" alt="" loading="lazy"></span>
  <span class="e-name">Furball Pup</span><span class="e-sub">combi</span>
</a>
"""


def test_parses_own_category_cards():
    items = parse_list_page(SAMPLE, "cookies")
    assert [i["id"] for i in items] == ["ch40", "ch85"]
    assert items[0] == {
        "id": "ch40",
        "name": "Tiger Lily Cookie",
        "grade": "L",
        "sub": "ขว้างหอก",
        "slug": "ch40",
    }


def test_unescapes_html_entities_in_names():
    items = parse_list_page(SAMPLE, "cookies")
    assert items[1]["name"] == "Admiral Gimbap Cookie"
    assert items[1]["sub"] == "Admiral's Charge"


def test_foreign_category_icons_excluded():
    pets = parse_list_page(SAMPLE, "pets")
    assert [i["id"] for i in pets] == ["pet53"]


def test_empty_page_yields_no_items():
    assert parse_list_page("<html><body>nothing here</body></html>", "cookies") == []
