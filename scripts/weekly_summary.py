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

def generate_weekly_summary(client: anthropic.Anthropic, articles: list[dict]) -> str:
    if not articles:
        return (
            "Deze week zijn er geen nieuwe artikelen over robotica in de zorg "
            "verzameld. Kom volgende week weer terug voor een nieuw overzicht."
        )

    articles_text = "\n\n".join(
        f"- [{a['categorie']}] {a['title']} ({a['source']}): {a['samenvatting']}"
        for a in articles
    )

    prompt = f"""Je bent eindredacteur van een Nederlandse nieuwsbrief over robotica in de gezondheidszorg.

Hieronder staan alle artikelen die deze week zijn verzameld:

{articles_text}

Schrijf een doorlopende, samenhangende samenvatting (geen lijst, geen opsommingstekens)
van ongeveer 250-400 woorden, als een nieuwsbrief-artikel. Vereisten:
- Begin met een korte intro-zin over de week in het algemeen
- Behandel de belangrijkste ontwikkelingen in lopende tekst, gegroepeerd waar dat
  logisch is per thema (bijv. chirurgie, revalidatie, zorgrobots)
- Leg waar relevant uit waarom iets belangrijk is, niet alleen wat er gebeurde
- Schrijf in helder, professioneel Nederlands, geschikt voor een geïnteresseerde
  leek of zorgprofessional
- Geen kopjes, geen bullet points — gewoon doorlopende alinea's
- Verzin geen feiten die niet in de input staan

Schrijf alleen de samenvattende tekst, zonder inleidende zin zoals "Hier is de samenvatting"."""

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Opslaan in archief (zodat oude weekoverzichten ook terug te vinden zijn)
# ---------------------------------------------------------------------------

def save_weekly_summary(summary: str, week_start: str, week_end: str, article_count: int) -> list[dict]:
    os.makedirs(DATA_DIR, exist_ok=True)
    history = []
    if os.path.exists(WEEKLY_ARCHIVE_FILE):
        with open(WEEKLY_ARCHIVE_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

    history.append({
        "week_start": week_start,
        "week_end": week_end,
        "summary": summary,
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
        blocks.append(f"""<section class="week-block">
  <h2>Week van {week['week_start']} t/m {week['week_end']} ({week['article_count']} artikelen)</h2>
  {paragraphs}
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

def send_email_via_resend(summary: str, week_start: str, week_end: str) -> None:
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

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, Arial, sans-serif; background:#f4f4f5; padding: 24px;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;padding:28px 32px;">
    <h1 style="font-size:20px;margin:0 0 4px;color:#0f1419;">📰 Weekoverzicht: Robotica in de Zorg</h1>
    <p style="color:#8b96a3;font-size:13px;margin:0 0 24px;">Week van {week_start} t/m {week_end}</p>
    {paragraphs_html}
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

Commit changes
Actions → Wekelijks weekoverzicht (zondag) → Run workflow
Kijk weer in de log bij die stap, en plak nu de regel "Resend foutdetails: ..." hier — die geeft het exacte antwoord van Resend over waarom het geweigerd wordt.
Claude Fable 5 is currently unavailable.


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
    summary = generate_weekly_summary(client, week_articles)

    history = save_weekly_summary(summary, week_start, week_end, len(week_articles))
    render_weekly_page(history)
    print(f"Weekoverzicht-pagina geschreven naar {OUTPUT_HTML}")

    send_email_via_resend(summary, week_start, week_end)

    print("Klaar.")


if __name__ == "__main__":
    main()
