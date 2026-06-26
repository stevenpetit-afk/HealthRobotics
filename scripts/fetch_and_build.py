#!/usr/bin/env python3
"""
Haalt dagelijks nieuws op over robotica in de zorg (via Google News RSS),
laat Claude elk artikel kort samenvatten/categoriseren, en bouwt een
statische HTML-site met de resultaten, gegroepeerd per categorie.
"""

import os
import re
import json
import time
import hashlib
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import anthropic

# ---------------------------------------------------------------------------
# Configuratie
# ---------------------------------------------------------------------------

CATEGORIES = {
    "chirurgie": "surgical robot OR robotic surgery hospital",
    "revalidatie": "rehabilitation robot OR exoskeleton therapy patient",
    "diagnostiek": "diagnostic robot OR AI robot imaging healthcare",
    "verpleging-ouderenzorg": "nursing robot OR elderly care robot OR care assistant robot",
    "logistiek-ziekenhuis": "hospital logistics robot OR pharmacy robot OR delivery robot hospital",
}

MAX_ARTICLES_PER_CATEGORY = 6
DATA_DIR = "data"
SITE_DIR = "docs"
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")
DAYS_TO_KEEP_ON_HOMEPAGE = 14

ANTHROPIC_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Nieuws ophalen
# ---------------------------------------------------------------------------

def fetch_rss(query: str) -> list[dict]:
    """Haalt artikelen op van Google News RSS voor een zoekopdracht."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()

    root = ET.fromstring(raw)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        description = (item.findtext("description") or "").strip()
        # Google News description bevat vaak HTML; strip dat ruwweg
        description = re.sub(r"<[^>]+>", "", description)

        if not title or not link:
            continue

        items.append({
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "source": source,
            "description": description,
        })
    return items


def article_id(article: dict) -> str:
    """Stabiele id voor dedupe, gebaseerd op titel + bron."""
    key = f"{article['title']}|{article['source']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Samenvatten met Claude
# ---------------------------------------------------------------------------

def summarize_article(client: anthropic.Anthropic, article: dict, category: str) -> dict | None:
    """
    Vraagt Claude om een korte NL-samenvatting en relevantie-check.
    Geeft None terug als het artikel niet relevant genoeg is.
    """
    prompt = f"""Je krijgt een nieuwsartikel-titel en beschrijving over robotica in de zorg.

Titel: {article['title']}
Bron: {article['source']}
Beschrijving: {article['description'][:600]}

Categorie waar dit artikel onder gezocht is: {category}

Taak:
1. Beoordeel of dit artikel daadwerkelijk relevant is voor "robotica in de gezondheidszorg" (chirurgische robots, revalidatierobots, zorgrobots, ziekenhuislogistiek, diagnostische AI-robots, etc.). Puur AI-nieuws zonder robotica-component, of niet-zorg-gerelateerd robotnieuws, is NIET relevant.
2. Als relevant: schrijf een neutrale, feitelijke samenvatting in het Nederlands van 2-3 zinnen.
3. Geef de meest passende categorie terug uit deze lijst: chirurgie, revalidatie, diagnostiek, verpleging-ouderenzorg, logistiek-ziekenhuis, overig.

Antwoord ALLEEN met JSON, niets anders, in dit exacte formaat:
{{"relevant": true of false, "samenvatting": "...", "categorie": "..."}}"""

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```json\s*|\s*```$", "", text.strip())
        data = json.loads(text)

        if not data.get("relevant"):
            return None

        return {
            "samenvatting": data.get("samenvatting", "").strip(),
            "categorie": data.get("categorie", category).strip(),
        }
    except Exception as e:
        print(f"  [waarschuwing] samenvatten mislukt voor '{article['title'][:60]}': {e}")
        return None


# ---------------------------------------------------------------------------
# Data persistentie (dedupe over dagen heen)
# ---------------------------------------------------------------------------

def load_seen() -> dict:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def load_archive() -> list[dict]:
    archive_file = os.path.join(DATA_DIR, "archive.json")
    if os.path.exists(archive_file):
        with open(archive_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_archive(archive: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    archive_file = os.path.join(DATA_DIR, "archive.json")
    # bewaar maximaal 60 dagen aan data om bestand niet te laten groeien
    cutoff = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    archive = [a for a in archive if a["date_added"] >= cutoff]
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# HTML genereren
# ---------------------------------------------------------------------------

CATEGORY_LABELS = {
    "chirurgie": "Chirurgie",
    "revalidatie": "Revalidatie",
    "diagnostiek": "Diagnostiek",
    "verpleging-ouderenzorg": "Verpleging & Ouderenzorg",
    "logistiek-ziekenhuis": "Ziekenhuislogistiek",
    "overig": "Overig",
}

CATEGORY_ICONS = {
    "chirurgie": "🔬",
    "revalidatie": "🦾",
    "diagnostiek": "🩻",
    "verpleging-ouderenzorg": "🤝",
    "logistiek-ziekenhuis": "🏥",
    "overig": "📰",
}

CATEGORY_DESCRIPTIONS = {
    "chirurgie": "Robotisch-geassisteerde operaties, minimaal invasieve chirurgie en chirurgische precisie-systemen.",
    "revalidatie": "Exoskeletten, therapierobots en technologie die patiënten helpt te herstellen en zelfstandig te bewegen.",
    "diagnostiek": "AI- en robotsystemen die artsen helpen bij beeldvorming, analyse en vroege opsporing van aandoeningen.",
    "verpleging-ouderenzorg": "Zorgrobots, sociale robots en assistentietechnologie voor verpleging en ouderenzorg.",
    "logistiek-ziekenhuis": "Autonome robots voor medicijnbezorging, ziekenhuislogistiek en interne transportprocessen.",
    "overig": "Overige ontwikkelingen op het snijvlak van robotica en gezondheidszorg.",
}

# Gedeelde CSS voor alle pagina's
SHARED_CSS = """
  :root {
    --bg: #0f1419;
    --card: #1a2128;
    --accent: #4fd1c5;
    --text: #e6edf3;
    --muted: #8b96a3;
    --border: #2a333d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  header {
    padding: 2.5rem 1.5rem 1.5rem;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }
  header h1 { margin: 0 0 0.4rem; font-size: 1.8rem; }
  header p { color: var(--muted); margin: 0; font-size: 0.95rem; }
  nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    padding: 1.2rem 1rem;
    border-bottom: 1px solid var(--border);
  }
  nav a {
    color: var(--muted);
    text-decoration: none;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.85rem;
  }
  nav a:hover, nav a.active { color: var(--accent); border-color: var(--accent); }
  main { max-width: 760px; margin: 0 auto; padding: 1.5rem 1.2rem 4rem; }
  article.item {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin: 0.9rem 0;
  }
  article.item h3 { margin: 0 0 0.4rem; font-size: 1.02rem; }
  article.item h3 a { color: var(--text); text-decoration: none; }
  article.item h3 a:hover { color: var(--accent); }
  article.item p { margin: 0.3rem 0 0.5rem; color: var(--text); font-size: 0.92rem; }
  article.item .meta { font-size: 0.78rem; color: var(--muted); }
  footer { text-align: center; color: var(--muted); font-size: 0.8rem; padding: 2rem 1rem; }
  .empty { color: var(--muted); text-align: center; padding: 3rem 1rem; }
"""


def nav_html(active_cat: str | None, by_category: dict) -> str:
    """Genereert de navigatiebalk met links naar subpagina's."""
    links = []
    links.append(
        f'<a href="index.html"{"class=\"active\"" if active_cat is None else ""}>🏠 Home</a>'
    )
    for cat in CATEGORY_LABELS:
        if cat not in by_category:
            continue
        icon = CATEGORY_ICONS.get(cat, "")
        label = CATEGORY_LABELS[cat]
        active = ' class="active"' if cat == active_cat else ""
        links.append(f'<a href="{cat}.html"{active}>{icon} {label}</a>')
    links.append('<a href="weekoverzicht.html">📰 Weekoverzicht</a>')
    return "\n".join(links)


def render_article(item: dict) -> str:
    return f"""<article class="item">
  <h3><a href="{item['link']}" target="_blank" rel="noopener">{item['title']}</a></h3>
  <p>{item['samenvatting']}</p>
  <div class="meta">{item['source']} · {item['date_added']}</div>
</article>"""


def render_homepage(by_category: dict, updated: str, nav: str) -> str:
    """Hoofdpagina: intro + 3 meest recente artikelen per categorie als preview."""
    sections = []
    for cat in CATEGORY_LABELS:
        if cat not in by_category:
            continue
        label = CATEGORY_LABELS[cat]
        icon = CATEGORY_ICONS.get(cat, "")
        desc = CATEGORY_DESCRIPTIONS.get(cat, "")
        preview_items = by_category[cat][:3]
        items_html = "".join(render_article(a) for a in preview_items)
        total = len(by_category[cat])
        meer = f'<p style="text-align:right;margin:0.5rem 0 0;"><a href="{cat}.html" style="color:var(--accent);font-size:0.85rem;text-decoration:none;">Alle {total} artikelen →</a></p>' if total > 3 else ""
        sections.append(f"""<section style="margin-bottom:2.8rem;">
  <div style="display:flex;align-items:baseline;gap:0.5rem;border-bottom:1px solid var(--border);padding-bottom:0.5rem;margin-bottom:0.2rem;">
    <h2 style="font-size:1.2rem;color:var(--accent);margin:0;">{icon} {label}</h2>
    <a href="{cat}.html" style="font-size:0.8rem;color:var(--muted);text-decoration:none;margin-left:auto;">Alle artikelen →</a>
  </div>
  <p style="color:var(--muted);font-size:0.85rem;margin:0.4rem 0 0.8rem;">{desc}</p>
  {items_html}
  {meer}
</section>""")

    if not sections:
        content = '<p class="empty">Nog geen artikelen verzameld. Kom morgen terug!</p>'
    else:
        content = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robotica in de Zorg — Dagelijks Nieuws</title>
<style>{SHARED_CSS}
  .intro {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 2rem;
    font-size: 0.95rem;
    color: var(--muted);
    line-height: 1.6;
  }}
</style>
</head>
<body>
<header>
  <h1>🤖 Robotica in de Zorg</h1>
  <p>Dagelijks automatisch verzameld nieuws — bijgewerkt op {updated}</p>
</header>
<nav>{nav}</nav>
<main>
  <div class="intro">
    Welkom bij <strong style="color:var(--text);">Robotica in de Zorg</strong> — een dagelijks bijgewerkt nieuwsoverzicht
    over de nieuwste ontwikkelingen op het snijvlak van robotica en gezondheidszorg.
    Kies een categorie in het menu hierboven of blader hieronder door de meest recente artikelen per thema.
  </div>
  {content}
</main>
<footer>Automatisch gegenereerd met Google News RSS &amp; Claude · {updated}</footer>
</body>
</html>"""


def render_category_page(cat: str, items: list[dict], updated: str, nav: str) -> str:
    """Subpagina voor één categorie met alle artikelen."""
    label = CATEGORY_LABELS.get(cat, cat)
    icon = CATEGORY_ICONS.get(cat, "")
    desc = CATEGORY_DESCRIPTIONS.get(cat, "")
    items_html = "".join(render_article(a) for a in items)

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{label} — Robotica in de Zorg</title>
<style>{SHARED_CSS}</style>
</head>
<body>
<header>
  <h1>{icon} {label}</h1>
  <p>{desc}</p>
</header>
<nav>{nav}</nav>
<main>
  <p style="color:var(--muted);font-size:0.85rem;margin:0 0 1.2rem;">{len(items)} artikel(en) van de afgelopen 14 dagen</p>
  {items_html if items_html else '<p class="empty">Nog geen artikelen in deze categorie.</p>'}
</main>
<footer>Automatisch gegenereerd met Google News RSS &amp; Claude · {updated}</footer>
</body>
</html>"""


def render_site(archive: list[dict]) -> None:
    os.makedirs(SITE_DIR, exist_ok=True)
    today = datetime.date.today()
    updated = today.strftime("%d-%m-%Y")
    cutoff = (today - datetime.timedelta(days=DAYS_TO_KEEP_ON_HOMEPAGE)).isoformat()

    recent = [a for a in archive if a["date_added"] >= cutoff]

    by_category: dict[str, list[dict]] = {}
    for a in recent:
        by_category.setdefault(a["categorie"], []).append(a)
    for items in by_category.values():
        items.sort(key=lambda x: x["date_added"], reverse=True)

    # Navigatie (zonder actieve pagina voor homepage)
    nav_home = nav_html(None, by_category)

    # Hoofdpagina
    homepage_html = render_homepage(by_category, updated, nav_home)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(homepage_html)

    # Subpagina per categorie
    for cat in CATEGORY_LABELS:
        items = by_category.get(cat, [])
        nav_cat = nav_html(cat, by_category)
        cat_html = render_category_page(cat, items, updated, nav_cat)
        with open(os.path.join(SITE_DIR, f"{cat}.html"), "w", encoding="utf-8") as f:
            f.write(cat_html)


# ---------------------------------------------------------------------------
# Hoofdproces
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY ontbreekt als environment variable.")

    client = anthropic.Anthropic(api_key=api_key)

    seen = load_seen()
    archive = load_archive()
    today_str = datetime.date.today().isoformat()

    new_count = 0

    for category, query in CATEGORIES.items():
        print(f"Ophalen: {category} ...")
        try:
            articles = fetch_rss(query)
        except Exception as e:
            print(f"  [fout] kon RSS niet ophalen voor {category}: {e}")
            continue

        added_for_category = 0
        for article in articles:
            if added_for_category >= MAX_ARTICLES_PER_CATEGORY:
                break

            aid = article_id(article)
            if aid in seen:
                continue

            result = summarize_article(client, article, category)
            seen[aid] = today_str  # ook niet-relevante markeren als gezien, om herhaalde checks te voorkomen
            time.sleep(0.3)  # lichte rate-limit beleefdheid

            if result is None:
                continue

            archive.append({
                "id": aid,
                "title": article["title"],
                "link": article["link"],
                "source": article["source"],
                "samenvatting": result["samenvatting"],
                "categorie": result["categorie"],
                "date_added": today_str,
            })
            added_for_category += 1
            new_count += 1

        print(f"  {added_for_category} nieuwe relevante artikelen toegevoegd.")

    save_seen(seen)
    save_archive(archive)
    render_site(archive)

    print(f"\nKlaar. {new_count} nieuwe artikelen toegevoegd. Site gegenereerd in {SITE_DIR}/index.html")


if __name__ == "__main__":
    main()
