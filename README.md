# Robotica in de Zorg — Dagelijks Nieuws

Een volledig automatische site die elke dag nieuws over robotica in de
gezondheidszorg verzamelt, samenvat en publiceert. Geen server, geen
handmatige goedkeuring nodig.

## Hoe het werkt

1. **GitHub Actions** draait elke dag (07:00 NL-tijd) `scripts/fetch_and_build.py`
2. Het script haalt nieuws op via **Google News RSS** voor 5 categorieën:
   chirurgie, revalidatie, diagnostiek, verpleging & ouderenzorg, ziekenhuislogistiek
3. Elk artikel wordt naar de **Claude API** gestuurd om te checken of het
   relevant is en om een Nederlandse samenvatting te maken
4. Het script bouwt `site/index.html` opnieuw
5. De wijzigingen worden automatisch gecommit en gepusht
6. **GitHub Pages** serveert die `site/`-map als je website

Artikelen die al eerder gezien zijn worden niet opnieuw verwerkt
(bijgehouden in `data/seen.json`). De homepage toont de laatste 14 dagen
aan nieuws; oudere data blijft 60 dagen bewaard in `data/archive.json`.

## Installatie (eenmalig, ~10 minuten)

### 1. Maak een GitHub-repository
- Ga naar github.com → New repository → bijv. `robotica-zorg-nieuws`
- Maak hem **public** (nodig voor gratis GitHub Pages, tenzij je GitHub Pro hebt)

### 2. Upload deze bestanden
Upload deze hele mapstructuur naar je nieuwe repository:
```
.github/workflows/daily.yml
scripts/fetch_and_build.py
README.md
```
(De mappen `data/` en `site/` worden automatisch aangemaakt door het script.)

### 3. Voeg je Anthropic API key toe als secret
- Ga in je repo naar **Settings → Secrets and variables → Actions**
- Klik **New repository secret**
- Naam: `ANTHROPIC_API_KEY`
- Waarde: jouw API key van [console.anthropic.com](https://console.anthropic.com)

### 4. Zet GitHub Pages aan
- Ga naar **Settings → Pages**
- Bij "Build and deployment" → Source: **Deploy from a branch**
- Branch: `main`, map: `/site`
- Opslaan

### 5. Test de workflow handmatig
- Ga naar het tabblad **Actions**
- Klik op "Dagelijks robotica-zorg nieuws" → **Run workflow**
- Na ~1-2 minuten verschijnt je site op
  `https://<jouw-gebruikersnaam>.github.io/<repo-naam>/`

Vanaf nu draait dit elke dag vanzelf. Je hoeft niets meer te doen.

## Aanpassen

- **Categorieën/zoekopdrachten wijzigen**: pas `CATEGORIES` bovenin
  `scripts/fetch_and_build.py` aan
- **Aantal artikelen per categorie**: `MAX_ARTICLES_PER_CATEGORY`
- **Tijdstip van de dagelijkse run**: de `cron`-regel in
  `.github/workflows/daily.yml` (tijden zijn in UTC)
- **Uiterlijk van de site**: `PAGE_TEMPLATE`-variabele in het script (CSS)
- **Hoe lang nieuws op de homepage blijft staan**: `DAYS_TO_KEEP_ON_HOMEPAGE`

## Kosten

- GitHub Actions: gratis voor publieke repo's
- GitHub Pages hosting: gratis
- Google News RSS: gratis, geen key nodig
- Claude API: betaald per gebruik — bij ~25 artikelen/dag met Sonnet kost
  dit naar schatting een paar dollarcent per dag
