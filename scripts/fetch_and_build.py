
#!/usr/bin/env python3
"""
Haalt dagelijks nieuws op over robotica in de zorg (via Google News RSS),
laat Claude elk artikel samenvatten in NL én EN, en bouwt een tweetalige
statische HTML-site: docs/ (NL) en docs/en/ (EN).
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
    "verpleging-ouderenzorg": "nursing robot OR elderly care robot OR care assistant robot",
    "logistiek-ziekenhuis": "hospital logistics robot OR pharmacy robot OR delivery robot hospital",
    "diagnostiek": "diagnostic robot OR AI robot imaging healthcare",
    "chirurgie": "surgical robot OR robotic surgery hospital",
    "revalidatie": "rehabilitation robot OR exoskeleton therapy patient",
    "bedrijfsnieuws": "healthcare robotics company acquisition partnership funding OR medical robot market",
}
 
MAX_ARTICLES_PER_CATEGORY = 6
DATA_DIR = "data"
SITE_DIR = "docs"
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")
DAYS_TO_KEEP_ON_HOMEPAGE = 30
ANTHROPIC_MODEL = "claude-sonnet-4-6"
 
BLOCKED_DOMAINS = [
    "newswire.com", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "accesswire.com", "einpresswire.com",
    "prlog.org", "send2press.com", "pr.com", "przoom.com",
    "marketwired.com", "markets.businessinsider.com",
]
 
# ---------------------------------------------------------------------------
# Taalconfiguratie
# ---------------------------------------------------------------------------
 
NL = {
    "lang": "nl",
    "dir": "",           # docs/
    "other_lang_dir": "en/",
    "flag": "🇬🇧",
    "switch_label": "English",
    "site_title": "Robots in Healthcare",
    "site_subtitle": "Dagelijks automatisch verzameld nieuws — bijgewerkt op {updated}",
    "intro": "Welkom bij <strong style=\"color:var(--text);\">Robots in Healthcare</strong> — een dagelijks bijgewerkt nieuwsoverzicht over de nieuwste ontwikkelingen op het snijvlak van robotica en gezondheidszorg. Kies een categorie in het menu hierboven of blader hieronder door de meest recente artikelen per thema.",
    "all_articles": "Alle {n} artikelen →",
    "articles_count": "{n} artikel(en) van de afgelopen 14 dagen",
    "weekly": "📰 Weekoverzicht",
    "weekly_file": "weekoverzicht.html",
    "home": "🏠 Home",
    "footer": "Automatisch gegenereerd met Google News RSS & Claude · {updated}",
    "empty": "Nog geen artikelen verzameld. Kom morgen terug!",
    "empty_cat": "Nog geen artikelen in deze categorie.",
    "summary_key": "samenvatting",
    "category_labels": {
        "verpleging-ouderenzorg": "Verpleging & Ouderenzorg",
        "logistiek-ziekenhuis": "Ziekenhuislogistiek",
        "diagnostiek": "Diagnostiek",
        "chirurgie": "Chirurgie",
        "revalidatie": "Revalidatie",
        "bedrijfsnieuws": "Bedrijfsnieuws",
        "overig": "Overig",
    },
    "category_descriptions": {
        "verpleging-ouderenzorg": "Zorgrobots, sociale robots en assistentietechnologie voor verpleging en ouderenzorg.",
        "logistiek-ziekenhuis": "Autonome robots voor medicijnbezorging, ziekenhuislogistiek en interne transportprocessen.",
        "diagnostiek": "AI- en robotsystemen die artsen helpen bij beeldvorming, analyse en vroege opsporing van aandoeningen.",
        "chirurgie": "Robotisch-geassisteerde operaties, minimaal invasieve chirurgie en chirurgische precisie-systemen.",
        "revalidatie": "Exoskeletten, therapierobots en technologie die patiënten helpt te herstellen en zelfstandig te bewegen.",
        "bedrijfsnieuws": "Bedrijfsontwikkelingen, overnames, partnerships en marktinformatie over zorgrobotica-bedrijven.",
        "overig": "Overige ontwikkelingen op het snijvlak van robotica en gezondheidszorg.",
    },
}
 
EN = {
    "lang": "en",
    "dir": "en/",        # docs/en/
    "other_lang_dir": "../",
    "flag": "🇳🇱",
    "switch_label": "Nederlands",
    "site_title": "Robots in Healthcare",
    "site_subtitle": "Daily automated news — updated on {updated}",
    "intro": "Welcome to <strong style=\"color:var(--text);\">Robots in Healthcare</strong> — a daily overview of the latest developments at the intersection of robotics and healthcare. Choose a category in the menu above or browse the most recent articles by topic below.",
    "all_articles": "All {n} articles →",
    "articles_count": "{n} article(s) from the past 14 days",
    "weekly": "📰 Weekly digest",
    "weekly_file": "../weekoverzicht.html",
    "home": "🏠 Home",
    "footer": "Automatically generated with Google News RSS & Claude · {updated}",
    "empty": "No articles collected yet. Check back tomorrow!",
    "empty_cat": "No articles in this category yet.",
    "summary_key": "summary",
    "category_labels": {
        "verpleging-ouderenzorg": "Nursing & Elderly Care",
        "logistiek-ziekenhuis": "Hospital Logistics",
        "diagnostiek": "Diagnostics",
        "chirurgie": "Surgery",
        "revalidatie": "Rehabilitation",
        "bedrijfsnieuws": "Business News",
        "overig": "Other",
    },
    "category_descriptions": {
        "verpleging-ouderenzorg": "Care robots, social robots and assistive technology for nursing and elderly care.",
        "logistiek-ziekenhuis": "Autonomous robots for medication delivery, hospital logistics and internal transport.",
        "diagnostiek": "AI and robotic systems helping doctors with imaging, analysis and early detection of conditions.",
        "chirurgie": "Robot-assisted operations, minimally invasive surgery and surgical precision systems.",
        "revalidatie": "Exoskeletons, therapy robots and technology helping patients recover and move independently.",
        "bedrijfsnieuws": "Company developments, acquisitions, partnerships and market information about healthcare robotics companies.",
        "overig": "Other developments at the intersection of robotics and healthcare.",
    },
}
 
CATEGORY_ICONS = {
    "verpleging-ouderenzorg": "🤝",
    "logistiek-ziekenhuis": "🏥",
    "diagnostiek": "🩻",
    "chirurgie": "🔬",
    "revalidatie": "🦾",
    "bedrijfsnieuws": "💼",
    "overig": "📰",
}
 
# ---------------------------------------------------------------------------
# Nieuws ophalen
# ---------------------------------------------------------------------------
 
def fetch_rss(query: str) -> list[dict]:
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
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        description = re.sub(r"<[^>]+>", "", (item.findtext("description") or "").strip())
        if not title or not link:
            continue
 
        # Domeinblokkade: sla persberichten en spam-domeinen over
        if any(domain in link for domain in BLOCKED_DOMAINS):
            continue
 
        # Datumfilter: sla artikelen ouder dan 7 dagen over
        pub_date_str = (item.findtext("pubDate") or "").strip()
        if pub_date_str:
            try:
                import email.utils
                pub_date = datetime.date(*email.utils.parsedate(pub_date_str)[:3])
                if (datetime.date.today() - pub_date).days > 7:
                    continue
            except Exception:
                pass  # bij parse-fout: artikel toch meenemen
 
        items.append({"title": title, "link": link, "source": source, "description": description})
    return items
 
 
def article_id(article: dict) -> str:
    key = f"{article['title']}|{article['source']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
 
 
# ---------------------------------------------------------------------------
# Samenvatten met Claude (NL + EN in één call)
# ---------------------------------------------------------------------------
 
def summarize_article(client: anthropic.Anthropic, article: dict, category: str) -> dict | None:
    prompt = f"""You receive a news article title and description about robotics in healthcare.
 
Title: {article['title']}
Source: {article['source']}
Description: {article['description'][:600]}
 
Category searched under: {category}
 
CONTEXT: This content is curated for the Erasmus MC Robotic Center in Rotterdam — a major academic medical center with active programs in surgical robotics, care robots, hospital logistics, and diagnostics. The audience is clinical and research professionals in a European academic hospital.
 
RELEVANCE CRITERIA — mark as relevant=true only if the article covers:
- Clinical outcomes or pilot/study results of robots in healthcare settings
- New or newly approved robotic products/systems for clinical use
- Policy, regulation, or reimbursement developments for healthcare robots
- Company news (partnerships, acquisitions, funding) related to healthcare robotics — assign these to "bedrijfsnieuws"
- Implementation or deployment of robots in hospitals or care settings
 
Mark as relevant=false if the article is about:
- Consumer/domestic robots (home assistants, toy robots, vacuum robots) — NOT healthcare
- Stock prices, earnings reports, or analyst price targets
- Milestone celebrations ("hospital performs 1000th robotic surgery") with no new clinical insight
- Pure AI/software without a robotics hardware component
- Non-healthcare industrial or military robots
 
GEOGRAPHIC PRIORITY: Prefer European content (EU hospitals, European companies, EU regulation). Include global content if clinically or scientifically significant.
 
CATEGORY ASSIGNMENT (pick the best fit):
- chirurgie: surgical robots, robot-assisted operations
- revalidatie: rehabilitation robots, exoskeletons, therapy robots
- diagnostiek: diagnostic robots, AI imaging systems with robotic component
- verpleging-ouderenzorg: care robots, nursing robots, social/assistive robots
- logistiek-ziekenhuis: hospital logistics, pharmacy robots, transport robots
- bedrijfsnieuws: company news, acquisitions, partnerships, funding, market reports
- overig: anything relevant that doesn't fit the above
 
If relevant, write summaries that are neutral and factual (2-3 sentences). Focus on: what the robot does, what results/outcomes were found, where it is used or being introduced.
 
Reply ONLY with JSON, nothing else:
{{"relevant": true or false, "samenvatting": "Dutch summary here (leave empty string if not relevant)", "summary": "English summary here (leave empty string if not relevant)", "categorie": "category"}}"""
 
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = re.sub(r"^```json\s*|\s*```$", "", response.content[0].text.strip())
        data = json.loads(text)
        if not data.get("relevant"):
            return None
        return {
            "samenvatting": data.get("samenvatting", "").strip(),
            "summary": data.get("summary", "").strip(),
            "categorie": data.get("categorie", category).strip(),
        }
    except Exception as e:
        print(f"  [warning] summarize failed for '{article['title'][:60]}': {e}")
        return None
 
 
# ---------------------------------------------------------------------------
# Data persistentie
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
    cutoff = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    archive = [a for a in archive if a["date_added"] >= cutoff]
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)
 
 
# ---------------------------------------------------------------------------
# HTML genereren
# ---------------------------------------------------------------------------
 
SHARED_CSS = """
  :root {
    --bg: #0f1419; --card: #1a2128; --accent: #4fd1c5;
    --text: #e6edf3; --muted: #8b96a3; --border: #2a333d;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
  header { padding: 2.5rem 1.5rem 1.5rem; text-align: center; border-bottom: 1px solid var(--border); position: relative; }
  header h1 { margin: 0 0 0.4rem; font-size: 1.8rem; }
  header p { color: var(--muted); margin: 0; font-size: 0.95rem; }
  .lang-switch { position: absolute; top: 1.2rem; right: 1.2rem; text-decoration: none; font-size: 1.4rem; line-height: 1; opacity: 0.8; }
  .lang-switch:hover { opacity: 1; }
  nav { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; padding: 1.2rem 1rem; border-bottom: 1px solid var(--border); }
  nav a { color: var(--muted); text-decoration: none; padding: 0.4rem 0.9rem; border: 1px solid var(--border); border-radius: 999px; font-size: 0.85rem; }
  nav a:hover, nav a.active { color: var(--accent); border-color: var(--accent); }
  main { max-width: 760px; margin: 0 auto; padding: 1.5rem 1.2rem 4rem; }
  article.item { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.2rem; margin: 0.9rem 0; }
  article.item h3 { margin: 0 0 0.4rem; font-size: 1.02rem; }
  article.item h3 a { color: var(--text); text-decoration: none; }
  article.item h3 a:hover { color: var(--accent); }
  article.item p { margin: 0.3rem 0 0.5rem; color: var(--text); font-size: 0.92rem; }
  article.item .meta { font-size: 0.78rem; color: var(--muted); }
  footer { text-align: center; color: var(--muted); font-size: 0.8rem; padding: 2rem 1rem; }
  .empty { color: var(--muted); text-align: center; padding: 3rem 1rem; }
  .intro { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem 1.4rem; margin-bottom: 2rem; font-size: 0.95rem; color: var(--muted); line-height: 1.6; }
"""
 
 
def nav_html(t: dict, active_cat: str | None, by_category: dict) -> str:
    prefix = "" if t["dir"] == "" else ""
    links = [f'<a href="{prefix}index.html"{"class=\"active\"" if active_cat is None else ""}>{t["home"]}</a>']
    for cat, label in t["category_labels"].items():
        if cat not in by_category:
            continue
        icon = CATEGORY_ICONS.get(cat, "")
        active = ' class="active"' if cat == active_cat else ""
        links.append(f'<a href="{prefix}{cat}.html"{active}>{icon} {label}</a>')
    links.append(f'<a href="{t["weekly_file"]}">{t["weekly"]}</a>')
    return "\n".join(links)
 
 
def render_article(item: dict, summary_key: str) -> str:
    summary = item.get(summary_key) or item.get("samenvatting", "")
    return f"""<article class="item">
  <h3><a href="{item['link']}" target="_blank" rel="noopener">{item['title']}</a></h3>
  <p>{summary}</p>
  <div class="meta">{item['source']} · {item['date_added']}</div>
</article>"""
 
 
def lang_switch_html(t: dict, other_file: str) -> str:
    return f'<a class="lang-switch" href="{t["other_lang_dir"]}{other_file}" title="{t["switch_label"]}">{t["flag"]}</a>'
 
 
def render_homepage(t: dict, by_category: dict, updated: str, nav: str, other_file: str = "index.html") -> str:
    sections = []
    for cat, label in t["category_labels"].items():
        if cat not in by_category:
            continue
        icon = CATEGORY_ICONS.get(cat, "")
        desc = t["category_descriptions"].get(cat, "")
        preview_items = by_category[cat][:3]
        items_html = "".join(render_article(a, t["summary_key"]) for a in preview_items)
        total = len(by_category[cat])
        prefix = "" if t["dir"] == "" else ""
        meer = f'<p style="text-align:right;margin:0.5rem 0 0;"><a href="{prefix}{cat}.html" style="color:var(--accent);font-size:0.85rem;text-decoration:none;">{t["all_articles"].format(n=total)}</a></p>' if total > 3 else ""
        sections.append(f"""<section style="margin-bottom:2.8rem;">
  <div style="display:flex;align-items:baseline;gap:0.5rem;border-bottom:1px solid var(--border);padding-bottom:0.5rem;margin-bottom:0.2rem;">
    <h2 style="font-size:1.2rem;color:var(--accent);margin:0;">{icon} {label}</h2>
    <a href="{prefix}{cat}.html" style="font-size:0.8rem;color:var(--muted);text-decoration:none;margin-left:auto;">{t["all_articles"].format(n=total)}</a>
  </div>
  <p style="color:var(--muted);font-size:0.85rem;margin:0.4rem 0 0.8rem;">{desc}</p>
  {items_html}
  {meer}
</section>""")
 
    content = "\n".join(sections) if sections else f'<p class="empty">{t["empty"]}</p>'
    switch = lang_switch_html(t, other_file)
 
    return f"""<!DOCTYPE html>
<html lang="{t['lang']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{t['site_title']} — Daily News</title>
<style>{SHARED_CSS}</style>
</head>
<body>
<header>
  {switch}
  <h1>🤖 {t['site_title']}</h1>
  <p>{t['site_subtitle'].format(updated=updated)}</p>
</header>
<nav>{nav}</nav>
<main>
  <div class="intro">{t['intro']}</div>
  {content}
</main>
<footer>{t['footer'].format(updated=updated)}</footer>
</body>
</html>"""
 
 
def render_category_page(t: dict, cat: str, items: list[dict], updated: str, nav: str, other_file: str) -> str:
    label = t["category_labels"].get(cat, cat)
    icon = CATEGORY_ICONS.get(cat, "")
    desc = t["category_descriptions"].get(cat, "")
    items_html = "".join(render_article(a, t["summary_key"]) for a in items)
    switch = lang_switch_html(t, other_file)
 
    return f"""<!DOCTYPE html>
<html lang="{t['lang']}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{label} — {t['site_title']}</title>
<style>{SHARED_CSS}</style>
</head>
<body>
<header>
  {switch}
  <h1>{icon} {label}</h1>
  <p>{desc}</p>
</header>
<nav>{nav}</nav>
<main>
  <p style="color:var(--muted);font-size:0.85rem;margin:0 0 1.2rem;">{t['articles_count'].format(n=len(items))}</p>
  {items_html if items_html else f'<p class="empty">{t["empty_cat"]}</p>'}
</main>
<footer>{t['footer'].format(updated=updated)}</footer>
</body>
</html>"""
 
 
def render_site(archive: list[dict]) -> None:
    os.makedirs(SITE_DIR, exist_ok=True)
    os.makedirs(os.path.join(SITE_DIR, "en"), exist_ok=True)
 
    today = datetime.date.today()
    updated = today.strftime("%d-%m-%Y")
    cutoff = (today - datetime.timedelta(days=DAYS_TO_KEEP_ON_HOMEPAGE)).isoformat()
 
    recent = [a for a in archive if a["date_added"] >= cutoff]
    by_category: dict[str, list[dict]] = {}
    for a in recent:
        by_category.setdefault(a["categorie"], []).append(a)
    for items in by_category.values():
        items.sort(key=lambda x: x["date_added"], reverse=True)
 
    for t, base_dir in [(NL, SITE_DIR), (EN, os.path.join(SITE_DIR, "en"))]:
        # Hoofdpagina
        nav = nav_html(t, None, by_category)
        html = render_homepage(t, by_category, updated, nav)
        with open(os.path.join(base_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
 
        # Subpagina's per categorie
        for cat in t["category_labels"]:
            items = by_category.get(cat, [])
            nav_cat = nav_html(t, cat, by_category)
            other_file = f"{cat}.html"
            cat_html = render_category_page(t, cat, items, updated, nav_cat, other_file)
            with open(os.path.join(base_dir, f"{cat}.html"), "w", encoding="utf-8") as f:
                f.write(cat_html)
 
 
# ---------------------------------------------------------------------------
# Hoofdproces
# ---------------------------------------------------------------------------
 
def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY missing.")
 
    client = anthropic.Anthropic(api_key=api_key)
    seen = load_seen()
    archive = load_archive()
    today_str = datetime.date.today().isoformat()
    new_count = 0
 
    for category, query in CATEGORIES.items():
        print(f"Fetching: {category} ...")
        try:
            articles = fetch_rss(query)
        except Exception as e:
            print(f"  [error] could not fetch RSS for {category}: {e}")
            continue
 
        added = 0
        for article in articles:
            if added >= MAX_ARTICLES_PER_CATEGORY:
                break
            aid = article_id(article)
            if aid in seen:
                continue
 
            result = summarize_article(client, article, category)
            seen[aid] = today_str
            time.sleep(0.3)
 
            if result is None:
                continue
 
            archive.append({
                "id": aid,
                "title": article["title"],
                "link": article["link"],
                "source": article["source"],
                "samenvatting": result["samenvatting"],
                "summary": result["summary"],
                "categorie": result["categorie"],
                "date_added": today_str,
            })
            added += 1
            new_count += 1
 
        print(f"  {added} new relevant articles added.")
 
    save_seen(seen)
    save_archive(archive)
    render_site(archive)
    print(f"\nDone. {new_count} new articles added. Site generated in {SITE_DIR}/")
 
 
if __name__ == "__main__":
    main()
