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

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robotica in de Zorg — Dagelijks Nieuws</title>
<style>
  :root {{
    --bg: #0f1419;
    --card: #1a2128;
    --accent: #4fd1c5;
    --text: #e6edf3;
    --muted: #8b96a3;
    --border: #2a333d;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  header {{
    padding: 2.5rem 1.5rem 1.5rem;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }}
  header h1 {{
    margin: 0 0 0.4rem;
    font-size: 1.8rem;
  }}
  header p {{
    color: var(--muted);
    margin: 0;
    font-size: 0.95rem;
  }}
  nav {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    padding: 1.2rem 1rem;
    border-bottom: 1px solid var(--border);
  }}
  nav a {{
    color: var(--muted);
    text-decoration: none;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.85rem;
  }}
  nav a:hover {{ color: var(--accent); border-color: var(--accent); }}
  main {{
    max-width: 760px;
    margin: 0 auto;
    padding: 1.5rem 1.2rem 4rem;
  }}
  section.category {{
    margin-bottom: 2.5rem;
  }}
  section.category h2 {{
    font-size: 1.2rem;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
  }}
  article.item {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin: 0.9rem 0;
  }}
  article.item h3 {{
    margin: 0 0 0.4rem;
    font-size: 1.02rem;
  }}
  article.item h3 a {{
    color: var(--text);
    text-decoration: none;
  }}
  article.item h3 a:hover {{ color: var(--accent); }}
  article.item p {{
    margin: 0.3rem 0 0.5rem;
    color: var(--text);
    font-size: 0.92rem;
  }}
  article.item .meta {{
    font-size: 0.78rem;
    color: var(--muted);
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    padding: 2rem 1rem;
  }}
  .empty {{
    color: var(--muted);
    text-align: center;
    padding: 3rem 1rem;
  }}
</style>
</head>
<body>
<header>
  <h1>🤖 Robotica in de Zorg</h1>
  <p>Dagelijks automatisch verzameld nieuws — laatst bijgewerkt op {updated}</p>
</header>
<nav>
{nav_links}
</nav>
<main>
{content}
</main>
<footer>
  Automatisch gegenereerd met Google News RSS &amp; Claude · {updated}
</footer>
</body>
</html>
"""


def render_site(archive: list[dict]) -> None:
    os.makedirs(SITE_DIR, exist_ok=True)
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=DAYS_TO_KEEP_ON_HOMEPAGE)).isoformat()

    recent = [a for a in archive if a["date_added"] >= cutoff]

    by_category: dict[str, list[dict]] = {}
    for a in recent:
        by_category.setdefault(a["categorie"], []).append(a)

    for items in by_category.values():
        items.sort(key=lambda x: x["date_added"], reverse=True)

    nav_links = "\n".join(
        f'<a href="#{cat}">{CATEGORY_LABELS.get(cat, cat)}</a>'
        for cat in CATEGORY_LABELS
        if cat in by_category
    )

    if not by_category:
        content = '<p class="empty">Nog geen artikelen verzameld. Kom morgen terug!</p>'
    else:
        sections = []
        for cat in CATEGORY_LABELS:
            if cat not in by_category:
                continue
            label = CATEGORY_LABELS[cat]
            items_html = []
            for item in by_category[cat]:
                items_html.append(f"""<article class="item">
  <h3><a href="{item['link']}" target="_blank" rel="noopener">{item['title']}</a></h3>
  <p>{item['samenvatting']}</p>
  <div class="meta">{item['source']} · {item['date_added']}</div>
</article>""")
            sections.append(f"""<section class="category" id="{cat}">
  <h2>{label}</h2>
  {''.join(items_html)}
</section>""")
        content = "\n".join(sections)

    html = PAGE_TEMPLATE.format(
        updated=today.strftime("%d-%m-%Y"),
        nav_links=nav_links,
        content=content,
    )

    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


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
