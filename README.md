# MobiData BW - Multimodales Routing & Scoring

Prototyp fuer multimodale Mobilitaetsbewertung in Baden-Wuerttemberg.
Nutzt offene Daten der [MobiData BW](https://www.mobidata-bw.de/) Plattform.

## Funktionen

- **Routen-Scoring**: Bewertet Mobilitaetsalternativen (Auto, OEPNV, Fahrrad, Fuss, P+R) nach Zeit, CO2 und Energie
- **GTFS-Daten**: Echte Fahrplandaten des OEPNV in Baden-Wuerttemberg
- **Verkehrsmeldungen**: Live-Daten zu Verkehrsstoerungen via MobiData BW API
- **Parkplatzdaten**: P+R und oeffentliche Parkplaetze aus der MobiData BW API
- **Ladestationen**: Standorte von E-Ladestationen
- **Wetterdaten**: Aktuelle Wetterbedingungen via Open-Meteo API

## Voraussetzungen

- Python 3.9+

## Installation

```bash
pip install -r requirements.txt
```

## Nutzung

### Scoring ausfuehren (Hauptskript)

Berechnet CO2, Energie und Gesamtscore fuer die Demo-Routen (Stuttgart - Freiburg):

```bash
python scoring_main.py
```

Ergebnis wird in `data/demo/routes_scored_demo.csv` gespeichert.

### Demo-Daten neu generieren

```bash
python scripts/setup_new_demo.py
```

### Wetterdaten abrufen

```bash
python scripts/fetch_weather.py
```

### Verkehrsmeldungen abrufen

```bash
python data/traffic/traffic_fetch.py
```

### Parkplatz-Subset erstellen

```bash
python data/parking/parking.py
```

## Projektstruktur

```
MobidataUI/
├── scoring_main.py              # Hauptskript: Scoring der Demo-Routen
├── requirements.txt
├── src/
│   ├── scoring/
│   │   ├── factors.py           # Lade-Funktionen fuer Emissions-/Energiefaktoren
│   │   └── scoring_demo.py      # Laedt vorberechnete Demo-Ergebnisse
│   └── utils/
│       └── weather.py           # Wetter-API (Open-Meteo) + Geocoding
├── scripts/
│   ├── fetch_weather.py         # Wetterdaten abrufen und speichern
│   └── setup_new_demo.py        # Demo-CSVs neu erzeugen
├── data/
│   ├── demo/                    # Demo-Routen und Scoring-Ergebnisse (CSV)
│   ├── gtfs/                    # GTFS-Fahrplandaten Baden-Wuerttemberg
│   ├── parking/                 # Parkplatzdaten (JSON/CSV)
│   ├── traffic/                 # Verkehrsmeldungen (XML/JSON/CSV)
│   ├── charging/                # E-Ladestationen (CSV)
│   └── weather/                 # Gespeicherte Wetterdaten
└── scoring_CSV/                 # Emissions- und Energiefaktoren pro Verkehrsmittel
```

## Datenquellen

| Quelle | Beschreibung |
|--------|-------------|
| [MobiData BW](https://www.mobidata-bw.de/) | GTFS, Verkehrsmeldungen, Parkplaetze |
| [Open-Meteo](https://open-meteo.com/) | Wetter-API (kostenlos, kein API-Key) |

## Scoring-Modell

Die Routen werden nach drei Kriterien bewertet:

- **Zeit** (Gewicht: 40%) - Gesamte Reisezeit in Minuten
- **CO2** (Gewicht: 40%) - CO2-Emissionen in Gramm
- **Energie** (Gewicht: 20%) - Energieverbrauch in Wh

Jedes Kriterium wird per Min-Max normalisiert. Der Gesamtscore (0-100) ergibt sich aus der gewichteten Summe.
