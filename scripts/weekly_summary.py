#!/usr/bin/env python3
"""
Wekelijkse samenvatting van robotica-in-de-zorg nieuws.

Leest data/archive.json (gevuld door fetch_and_build.py), selecteert de
artikelen van de afgelopen 7 dagen, laat Claude daar één doorlopende
nieuwsbrief-achtige samenvatting van schrijven, en:
  1. schrijft die samenvatting weg als pagina op de site (docs/weekoverzicht.html)
  2. verstuurt 'm als e-mail via Resend (als RESEND_API_KEY + EMAIL_TO gezet zijn)
"""

import os
import json
import datetime
import urllib.request
import urllib.error

import anthropic

DATA_DIR = "data"
DOCS_DIR = "docs"
ARCHIVE_FILE = os.path.join(DATA_DIR, "archive.json")
WEEKLY_ARCHIVE_FILE = os.path.join(DATA_DIR, "weekly_summaries.json")
OUTPUT_HTML = os.path.join(DOCS_DIR, "weekoverzicht.html")

ANTHROPIC_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Data inladen en selecteren
# ---------------------------------------------------------------------------

def load_archive() -> list[dict]:
    if not os.path.exists(ARCHIVE_FILE):
        return []
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def articles_from_last_week(archive: list[dict]) -> list[dict]:
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=7)).isoformat()
    return [a for a in archive if a["date_added"] >= cutoff]


# ---------------------------------------------------------------------------
# Samenvatting genereren met Claude
# ---------------------------------------------------------------------------

def generate_weekly_summary(client: anthropic.Anthropic, articles: list[dict]) -> dict:
    """
    Geeft een dict terug met:
      - "tekst": de doorlopende samenvatting
      - "top5": lijst van max. 5 dicts met titel, link, bron, en een korte reden
    """
    if not articles:
        return {
            "tekst": (
                "Deze week zijn er geen nieuwe artikelen over robotica in de zorg "
                "verzameld. Kom volgende week weer terug voor een nieuw overzicht."
            ),
            "top5": [],
        }

    # Geef elk artikel een kort referentienummer zodat Claude er ondubbelzinnig naar kan verwijzen
    indexed_articles = list(enumerate(articles, start=1))
    articles_text = "\n\n".join(
        f"[{i}] [{a['categorie']}] {a['title']} ({a['source']}): {a['samenvatting']}"
        for i, a in indexed_articles
    )

    prompt = f"""Je bent eindredacteur van een Nederlandse nieuwsbrief over robotica in de gezondheidszorg.

Hieronder staan alle artikelen die deze week zijn verzameld, elk met een nummer tussen [blokhaken]:

{articles_text}

Taak, twee onderdelen:

1. Schrijf een doorlopende, samenhangende samenvatting (geen lijst, geen opsommingstekens)
   van ongeveer 250-400 woorden, als een nieuwsbrief-artikel. Vereisten:
   - Begin met een korte intro-zin over de week in het algemeen
   - Behandel de belangrijkste ontwikkelingen in lopende tekst, gegroepeerd waar dat
     logisch is per thema (bijv. chirurgie, revalidatie, zorgrobots)
   - Leg waar relevant uit waarom iets belangrijk is, niet alleen wat er gebeurde
   - Schrijf in helder, professioneel Nederlands
   - Geen kopjes, geen bullet points binnen deze tekst — gewoon doorlopende alinea's
   - Verzin geen feiten die niet in de input staan

2. Selecteer de 5 (of minder als er minder dan 5 zijn) belangrijkste artikelen van de week.
   Belangrijk = grootste impact, meest vernieuwend, of meest relevant voor de zorgsector.
   Geef per artikel het nummer tussen [blokhaken], en een korte reden (max 15 woorden)
   waarom dit artikel in de top 5 staat.

Antwoord ALLEEN met JSON, niets anders, in dit exacte formaat:
{{
  "tekst": "de doorlopende samenvatting hier",
  "top5": [
    {{"nummer": 3, "reden": "korte reden waarom dit artikel belangrijk is"}},
    {{"nummer": 1, "reden": "..."}}
  ]
}}"""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.content[0].text.strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[waarschuwing] kon JSON-antwoord niet parsen: {e}")
        # Val terug op alleen de ruwe tekst, geen top5, zodat de run niet crasht
        return {"tekst": raw_text, "top5": []}

    article_by_number = dict(indexed_articles)
    top5 = []
    for entry in data.get("top5", [])[:5]:
        nummer = entry.get("nummer")
        artikel = article_by_number.get(nummer)
        if artikel is None:
            continue
        top5.append({
            "title": artikel["title"],
            "link": artikel["link"],
            "source": artikel["source"],
            "reden": entry.get("reden", "").strip(),
        })

    return {"tekst": data.get("tekst", "").strip(), "top5": top5}


# ---------------------------------------------------------------------------
# Opslaan in archief (zodat oude weekoverzichten ook terug te vinden zijn)
# ---------------------------------------------------------------------------

def save_weekly_summary(summary_text: str, top5: list[dict], week_start: str, week_end: str, article_count: int) -> list[dict]:
    os.makedirs(DATA_DIR, exist_ok=True)
    history = []
    if os.path.exists(WEEKLY_ARCHIVE_FILE):
        with open(WEEKLY_ARCHIVE_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

    history.append({
        "week_start": week_start,
        "week_end": week_end,
        "summary": summary_text,
        "top5": top5,
        "article_count": article_count,
    })
    # bewaar maximaal de laatste 26 weken (half jaar)
    history = history[-26:]

    with open(WEEKLY_ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return history


# ---------------------------------------------------------------------------
# HTML-pagina genereren
# ---------------------------------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weekoverzicht — Robotica in de Zorg</title>
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
    line-height: 1.6;
  }}
  header {{
    padding: 2.5rem 1.5rem 1.5rem;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }}
  header h1 {{ margin: 0 0 0.4rem; font-size: 1.8rem; }}
  header p {{ color: var(--muted); margin: 0; font-size: 0.95rem; }}
  nav {{
    display: flex;
    justify-content: center;
    gap: 0.5rem;
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
    max-width: 700px;
    margin: 0 auto;
    padding: 2rem 1.2rem 4rem;
  }}
  .week-block {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem 1.7rem;
    margin-bottom: 1.5rem;
  }}
  .week-block h2 {{
    font-size: 1.05rem;
    color: var(--accent);
    margin: 0 0 1rem;
  }}
  .week-block p {{
    margin: 0 0 1rem;
    font-size: 0.96rem;
  }}
  .week-block p:last-child {{ margin-bottom: 0; }}
  .top5 {{
    margin-top: 1.3rem;
    padding-top: 1.2rem;
    border-top: 1px solid var(--border);
  }}
  .top5 h3 {{
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    margin: 0 0 0.8rem;
  }}
  .top5 ol {{
    margin: 0;
    padding-left: 1.2rem;
  }}
  .top5 li {{
    margin-bottom: 0.7rem;
    font-size: 0.92rem;
  }}
  .top5 li:last-child {{ margin-bottom: 0; }}
  .top5 a {{
    color: var(--text);
    font-weight: 600;
    text-decoration: none;
  }}
  .top5 a:hover {{ color: var(--accent); }}
  .top5 .reden {{
    display: block;
    color: var(--muted);
    font-size: 0.85rem;
    margin-top: 0.15rem;
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    padding: 2rem 1rem;
  }}
</style>
</head>
<body>
<header>
  <h1>📰 Weekoverzicht</h1>
  <p>Een wekelijkse samenvatting van robotica-nieuws in de zorg, elke zondag</p>
</header>
<nav>
  <a href="index.html">← Terug naar alle nieuws</a>
</nav>
<main>
{content}
</main>
<footer>
  Automatisch gegenereerd met Claude · bijgewerkt op {updated}
</footer>
</body>
</html>
"""


def render_weekly_page(history: list[dict]) -> None:
    os.makedirs(DOCS_DIR, exist_ok=True)

    blocks = []
    for week in reversed(history):  # nieuwste bovenaan
        paragraphs = "".join(f"<p>{p}</p>" for p in week["summary"].split("\n\n") if p.strip())

        top5 = week.get("top5", [])
        top5_html = ""
        if top5:
            items = "".join(
                f"""<li>
  <a href="{item['link']}" target="_blank" rel="noopener">{item['title']}</a>
  <span class="reden">{item['source']} — {item['reden']}</span>
</li>"""
                for item in top5
            )
            top5_html = f"""<div class="top5">
  <h3>Top 5 belangrijkste artikelen</h3>
  <ol>{items}</ol>
</div>"""

        blocks.append(f"""<section class="week-block">
  <h2>Week van {week['week_start']} t/m {week['week_end']} ({week['article_count']} artikelen)</h2>
  {paragraphs}
  {top5_html}
</section>""")

    content = "\n".join(blocks) if blocks else "<p>Nog geen weekoverzichten beschikbaar.</p>"

    html = PAGE_TEMPLATE.format(
        content=content,
        updated=datetime.date.today().strftime("%d-%m-%Y"),
    )

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# E-mail versturen via Resend
# ---------------------------------------------------------------------------

def send_email_via_resend(summary: str, top5: list[dict], week_start: str, week_end: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    email_to = os.environ.get("EMAIL_TO")
    email_from = os.environ.get("EMAIL_FROM", "Robonews <onboarding@resend.dev>")

    if not api_key or not email_to:
        print("RESEND_API_KEY of EMAIL_TO niet gezet — e-mail wordt overgeslagen.")
        return

    paragraphs_html = "".join(
        f'<p style="margin:0 0 1rem;font-size:15px;line-height:1.6;color:#1a2128;">{p}</p>'
        for p in summary.split("\n\n") if p.strip()
    )

    top5_html = ""
    if top5:
        items_html = "".join(
            f"""<li style="margin-bottom:12px;font-size:14px;line-height:1.5;">
  <a href="{item['link']}" style="color:#0f1419;font-weight:600;text-decoration:none;">{item['title']}</a><br>
  <span style="color:#8b96a3;font-size:13px;">{item['source']} — {item['reden']}</span>
</li>"""
            for item in top5
        )
        top5_html = f"""
    <div style="margin-top:24px;padding-top:20px;border-top:1px solid #e5e5e5;">
      <h2 style="font-size:13px;text-transform:uppercase;letter-spacing:0.04em;color:#8b96a3;margin:0 0 14px;">Top 5 belangrijkste artikelen</h2>
      <ol style="margin:0;padding-left:20px;">{items_html}</ol>
    </div>"""

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, Arial, sans-serif; background:#f4f4f5; padding: 24px;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;padding:28px 32px;">
    <h1 style="font-size:20px;margin:0 0 4px;color:#0f1419;">📰 Weekoverzicht: Robotica in de Zorg</h1>
    <p style="color:#8b96a3;font-size:13px;margin:0 0 24px;">Week van {week_start} t/m {week_end}</p>
    {paragraphs_html}
    {top5_html}
  </div>
</body>
</html>"""

    payload = {
        "from": email_from,
        "to": [email_to],
        "subject": f"Weekoverzicht Robotica in de Zorg — {week_start} t/m {week_end}",
        "html": html_body,
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; robonews-bot/1.0)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = resp.read().decode("utf-8")
            print(f"E-mail verstuurd via Resend: {result}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[waarschuwing] e-mail versturen mislukt: HTTP {e.code}")
        print(f"Resend foutdetails: {error_body}")
    except Exception as e:
        print(f"[waarschuwing] e-mail versturen mislukt: {e}")


# ---------------------------------------------------------------------------
# Hoofdproces
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY ontbreekt als environment variable.")

    client = anthropic.Anthropic(api_key=api_key)

    archive = load_archive()
    week_articles = articles_from_last_week(archive)

    today = datetime.date.today()
    week_start = (today - datetime.timedelta(days=6)).isoformat()
    week_end = today.isoformat()

    print(f"Genereren weekoverzicht voor {week_start} t/m {week_end} ({len(week_articles)} artikelen)...")
    result = generate_weekly_summary(client, week_articles)
    summary_text = result["tekst"]
    top5 = result["top5"]
    print(f"  {len(top5)} artikelen geselecteerd voor de top 5.")

    history = save_weekly_summary(summary_text, top5, week_start, week_end, len(week_articles))
    render_weekly_page(history)
    print(f"Weekoverzicht-pagina geschreven naar {OUTPUT_HTML}")

    send_email_via_resend(summary_text, top5, week_start, week_end)

    print("Klaar.")


if __name__ == "__main__":
    main()
