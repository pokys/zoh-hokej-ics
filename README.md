# ZOH 2026 – hokej (ICS)

Generuje veřejné ICS kalendáře pro ZOH 2026 – hokej (ženy, muži a kombinovaný Česko).

## Co se generuje
- `dist/zoh-2026-hokej-zeny-cze.ics`
- `dist/zoh-2026-hokej-muzi-cze.ics`
- `dist/zoh-2026-hokej-cesko.ics`

## Odkazy (RAW)
- `https://raw.githubusercontent.com/pokys/zoh-hokej-ics/main/dist/zoh-2026-hokej-zeny-cze.ics`
- `https://raw.githubusercontent.com/pokys/zoh-hokej-ics/main/dist/zoh-2026-hokej-muzi-cze.ics`
- `https://raw.githubusercontent.com/pokys/zoh-hokej-ics/main/dist/zoh-2026-hokej-cesko.ics`

Obsah:
- skupinové zápasy české reprezentace
- všechny play-off zápasy (čtvrtfinále, semifinále, o bronz, finále) bez ohledu na účast Česka
- pokud jsou dvojice v play-off známé na Wikipedii, zobrazí se konkrétní týmy
- po odehrání zápasu se doplní skóre a typ konce (FT/OT/SO)

## Zdroje dat
- Wikipedia (program i průběžná skóre)

## Spuštění lokálně
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generate.py
```

## GitHub Actions
Workflow běží každých 6 hodin a je možné jej spustit ručně přes `workflow_dispatch`. Po vygenerování automaticky commitne změny v `dist/*.ics`.
