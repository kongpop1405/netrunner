"""Download game icons + item metadata from cookierundb.com — reference for templates.

    python tools/fetch_db_icons.py                        # cookies, pets, treasures
    python tools/fetch_db_icons.py --categories cookies
    python tools/fetch_db_icons.py --categories all --force

Icons land in snaps/cookierundb/<category>/<id>.png (git-ignored) with an
index.json per category mapping id -> name / grade / skill blurb. The icons are
pixel-identical to the in-game renders, so they work as a labeling reference
when cropping templates (know WHICH cookie/treasure a crop shows) and can match
directly on screens that render icons at a fixed size (inventory grid, gacha
result) after a one-time scale calibration. Gameplay templates still come from
tools/snap.py crops.

Existing files are skipped (resumable); --force re-downloads. Requests are
rate-limited — be polite, this is a fan-run site.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://cookierundb.com/th"
USER_AGENT = "netrunner-template-fetch/1.0 (personal CV-template reference)"
CATEGORIES = ["cookies", "pets", "treasures", "materials", "artifacts"]
REQUEST_GAP_S = 0.25

ECARD_RE = re.compile(r'<a class="ecard"(.*?)</a>', re.S)
HREF_RE = re.compile(r'href="[^"]*?/([^/"]+)"')
NAME_RE = re.compile(r'data-name="([^"]*)"')
GRADE_RE = re.compile(r'data-grade="([^"]*)"')
SUB_RE = re.compile(r'<span class="e-sub">(.*?)</span>', re.S)
ICON_RE = re.compile(r'src="[^"]*?assets/icons/([a-z]+)/([^"]+)\.png"')


def fetch(session: requests.Session, url: str, retries: int = 2) -> requests.Response:
    for attempt in range(retries + 1):
        try:
            res = session.get(url, timeout=15)
            if res.status_code == 200:
                return res
            if res.status_code in (429, 502, 503) and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            res.raise_for_status()
        except requests.RequestException:
            if attempt >= retries:
                raise
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"unreachable: {url}")


def parse_list_page(page_html: str, category: str) -> list[dict]:
    """One ecard = one item; the icon inside the card is its canonical game id."""
    items = []
    for m in ECARD_RE.finditer(page_html):
        card = m.group(1)
        icon = ICON_RE.search(card)
        # cards can embed foreign icons (combi cookie on a pet card) — keep own-category only
        if not icon or icon.group(1) != category:
            continue
        name = NAME_RE.search(card)
        grade = GRADE_RE.search(card)
        sub = SUB_RE.search(card)
        slug = HREF_RE.search(card)
        items.append({
            "id": icon.group(2),
            "name": html.unescape(name.group(1)) if name else "",
            "grade": grade.group(1) if grade else "",
            "sub": html.unescape(re.sub(r"<[^>]+>", "", sub.group(1))).strip() if sub else "",
            "slug": slug.group(1) if slug else "",
        })
    return items


def run_category(session: requests.Session, category: str, out_root: Path,
                 limit: int | None, force: bool) -> tuple[int, int]:
    res = fetch(session, f"{BASE}/{category}/")
    items = parse_list_page(res.text, category)
    if not items:
        print(f"warning: {category}: no ecards parsed — page layout may have changed", file=sys.stderr)
        return 0, 0
    if limit:
        items = items[:limit]

    out_dir = out_root / category
    out_dir.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = 0
    for i, item in enumerate(items, 1):
        dest = out_dir / f"{item['id']}.png"
        if dest.exists() and not force:
            skipped += 1
            continue
        icon = fetch(session, f"{BASE}/assets/icons/{category}/{item['id']}.png")
        dest.write_bytes(icon.content)
        downloaded += 1
        if downloaded % 50 == 0:
            print(f"  {category}: {i}/{len(items)} ...")
        time.sleep(REQUEST_GAP_S)

    index = out_dir / "index.json"
    index.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{category}: {len(items)} items -> {out_dir}  (downloaded {downloaded}, skipped {skipped})")
    return downloaded, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="download cookierundb icons + index.json per category")
    ap.add_argument("--categories", default="cookies,pets,treasures",
                    help=f"comma list or 'all' — available: {','.join(CATEGORIES)}")
    ap.add_argument("--out", default="snaps/cookierundb", help="output root (default: snaps/cookierundb)")
    ap.add_argument("--limit", type=int, default=None, help="max items per category (smoke test)")
    ap.add_argument("--force", action="store_true", help="re-download icons that already exist")
    args = ap.parse_args()

    wanted = CATEGORIES if args.categories == "all" else [c.strip() for c in args.categories.split(",")]
    unknown = [c for c in wanted if c not in CATEGORIES]
    if unknown:
        print(f"error: unknown categories {unknown} — available: {CATEGORIES}", file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    try:
        for category in wanted:
            run_category(session, category, Path(args.out), args.limit, args.force)
    except requests.RequestException as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
