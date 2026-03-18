# MobiDataUnified — Technische Architektur

Dieses Dokument beschreibt Infrastruktur, Datenverarbeitung, Routing-Algorithmen,
Scoring-Modell und CO₂-Bewertung des Systems. Erstellt als Grundlage für wissenschaftliche
Präsentationen und Paper-Dokumentation.

---

## 1. Infrastruktur

### Gesamtarchitektur

```
Browser (Leaflet.js SPA)
        │  HTTP/JSON
        ▼
FastAPI Backend (Python 3.11, uvicorn)
        │
        ├── Neo4j Graph DB ──── GTFS-Daten (ÖPNV BW)
        ├── SQLite          ──── Nutzerpräferenzen
        ├── OSRM API        ──── Autorouten & Distanzen (extern)
        ├── Nominatim/OSM   ──── Adress-Geocoding (extern)
        └── Open-Meteo API  ──── Wetterdaten (extern)
```

### Komponenten

| Komponente | Technologie | Zweck |
|---|---|---|
| **Backend** | FastAPI 0.115, Python 3.11 | REST-API, Routing-Logik, Scoring |
| **Graph-Datenbank** | Neo4j 5 Community | ÖPNV-Netzwerk als Graphstruktur |
| **Präferenzen** | SQLite (lokal) | Nutzereinstellungen persistent speichern |
| **Frontend** | Vanilla JS, Leaflet.js | Interaktive Karte, Eingabe, Ergebnisanzeige |
| **Containerisierung** | Docker Compose | Neo4j-Deployment |

### API-Endpunkte

| Methode | Pfad | Funktion |
|---|---|---|
| `POST` | `/route` | Multimodales Routing + Best-Match-Bewertung |
| `GET` | `/benchmark` | Algorithmenvergleich (Laufzeit, Knoten, Qualität) |
| `GET` | `/score-sensitivity` | Score mit 10 Gewichtungsvarianten |
| `GET` | `/api/stops/search` | Haltestellen-Autocomplete (GTFS-Daten) |
| `GET` | `/preferences` | Nutzerpräferenzen laden |
| `POST` | `/preferences` | Nutzerpräferenzen speichern |

---

## 2. Datenverarbeitung

### GTFS-Daten (Fahrplandaten Baden-Württemberg)

- **Quelle:** MobiData BW (mobidata-bw.de) — General Transit Feed Specification
- **Umfang:** ~779 MB Rohdaten, ca. 5.300 Haltestellen, 386.000 Verbindungen
- **Verarbeitung:** `gtfs_processor.py` filtert, normalisiert und importiert in Neo4j

**Verarbeitungsschritte:**

1. **Stopname-Normalisierung** — Umlaute, Sonderzeichen, Plattform-Suffixe vereinheitlichen
2. **SEV-Filter (Schienenersatzverkehr)** — Fahrten mit Keywords wie „SEV", „Ersatzverkehr",
   „Baustellenbus" werden aus dem Routing-Graphen ausgeschlossen
3. **Platform-Merging** — Haltestellen desselben Bahnhofs auf verschiedenen Bahnsteigen
   werden zu einem logischen Knoten zusammengefasst (kostenloser Umstieg: 1 Minute)
4. **Transfer-Kanten** — Umstiegsmöglichkeiten zwischen nahen Haltestellen
   (max. 300 m, 3 Minuten Fußweg) werden als eigene Graph-Kanten modelliert

**Neo4j-Graphstruktur:**

```
(:Stop {stop_id, name, lat, lon})
  -[:NEXT_STOP {departure, arrival, duration_min, route_name, route_type, trip_id}]->
(:Stop)
```

### Geocoding & Adressauflösung

- **Primär:** GTFS-Haltestellen-Suche (exakte Übereinstimmung über normalisierten Text)
- **Fallback:** Nominatim/OpenStreetMap für beliebige Adressen
- Koordinaten werden direkt übergeben, wenn GPS genutzt wird

### Park & Ride / Bike & Ride Stationen

- Quelle: MobiData BW (`park_ride.json`, `bike_ride.json`)
- Enthält: Name, Koordinaten, Kapazität, optional Echtzeit-Belegung
- Werden beim Start geladen und gecacht

---

## 3. Routing

### Verkehrsmodi

Das System berechnet parallel vier multimodale Routenoptionen:

| Modus | Beschreibung |
|---|---|
| **Nur Auto** | Direkte Autofahrt Start → Ziel via OSRM |
| **Park & Ride (P+R)** | Auto bis P+R-Station → ÖPNV bis Ziel |
| **Auto + ÖPNV (A+ÖV)** | Auto bis nächste ÖPNV-Haltestelle → ÖPNV bis Ziel |
| **Bike & Ride (B+R)** | Fahrrad bis B+R-Anlage → ÖPNV bis Ziel |

### Routing-Algorithmen

Alle drei Algorithmen arbeiten auf demselben In-Memory-Graphen (geladen aus Neo4j):

#### A* (Standard)
- Heuristik: Haversine-Distanz zum Ziel × Gewichtungsfaktor
- Findet optimalen Pfad deutlich schneller als Dijkstra durch zielgerichtete Suche
- Standard-Algorithmus in der Anwendung

#### Dijkstra (Referenz)
- Klassischer kürzeste-Pfad-Algorithmus, kein Vorwissen über Zielrichtung
- Garantiert optimales Ergebnis, höhere Knotenexpansion
- Wird für Validierung und Benchmarks verwendet

#### Greedy (Baseline)
- Wählt immer die lokal günstigste Verbindung ohne Rückblick
- Keine Optimierungsgarantie, sehr schnell
- Dient als untere Qualitätsgrenze im Vergleich

**Benchmark-Vergleich** (Endpunkt `/benchmark`):

| Metrik | A* | Dijkstra | Greedy |
|---|---|---|---|
| Laufzeit | niedrig | mittel | sehr niedrig |
| Knotenexpansion | niedrig | hoch | niedrig |
| Routenqualität | optimal | optimal | suboptimal |

### Zeitmodell

- Routing arbeitet rückwärts von der **gewünschten Ankunftszeit**
- Suchfenster: `[Ankunftszeit − 120 Minuten, Ankunftszeit]`
- Zeiten intern als **Minuten seit Mitternacht** (Integer)
- Transfer-Penalty: 10 Minuten Standard, 1 Minute für Bahnsteig-Umstieg am selben Bahnhof

### Distanzberechnung

- **Haversine-Formel** für Luftlinien-Distanzen (Fußweg, Fahrrad)
- **Detour-Index Auto:** 1,4 (reale Fahrstrecke ≈ 1,4 × Luftlinie)
- **Detour-Index Fahrrad:** 1,3
- **OSRM** für echte Autorouten-Geometrien (extern, öffentliche API)

---

## 4. Scoring — MAUT-Modell

Das **Best-Match-System** basiert auf dem **Multi-Attribute Utility Theory (MAUT)**-Ansatz —
einem entscheidungstheoretischen Modell ohne Trainingsdaten, das mehrere Kriterien
nachvollziehbar gewichtet.

### Kriterien und Gewichtung

```
Score(Modus) = w_CO₂ × U_CO₂ + w_Zeit × U_Zeit
               − Penalty_Komfort − Penalty_Wetter − Penalty_Distanz
```

| Kriterium | Standard-Gewicht | Beschreibung |
|---|---|---|
| **CO₂-Score (U_CO₂)** | 55 % | Normalisierte Emissionseinsparung vs. Auto |
| **Zeit-Score (U_Zeit)** | 45 % | Reisedauer relativ zur schnellsten Option |

### Nutzen-Normalisierung

- **Benefit-Normierung:** Höherer Wert = besser (z. B. mehr CO₂-Einsparung)
  `U = (Wert − Min) / (Max − Min)`
- **Cost-Normierung:** Niedrigerer Wert = besser (z. B. kürzere Reisezeit)
  `U = (Max − Wert) / (Max − Wert)`

### Penaltys (Abzüge)

| Penalty | Bedingung |
|---|---|
| **Distanz-Penalty** | Fahrrad- oder Fußstrecke überschreitet Nutzerpräferenz |
| **Temperatur-Penalty** | Temperatur unter Komfortgrenze für Fahrrad/Fußweg |
| **Regen-Penalty** | Niederschlag > 0,5 mm bei Fahrrad oder Fußweg |
| **Präferenz-Penalty** | Verkehrsmittel vom Nutzer deaktiviert |
| **Umstiegs-Penalty** | Mehrere Umstiege bei hohem Komfort-Gewicht |

### Score-Ausgabe

- Skala: **0 – 100** (höher = besser als Auto)
- Der Modus mit dem höchsten Score = **Best Match** (⭐)
- Erklärung: Pro Modus werden „Pluspunkte" und „Abzüge" im Klartext ausgegeben

### Profil-Schnellauswahl

| Profil | CO₂-Gewicht | Zeit-Gewicht |
|---|---|---|
| Ausgewogen | 55 % | 45 % |
| Umwelt | 80 % | 20 % |
| Schnell | 20 % | 80 % |

---

## 5. CO₂-Bewertung

### Emissionsfaktoren

Quelle: **Umweltbundesamt (UBA) 2024 — „Emissionsdaten Personenverkehr"**

| Verkehrsmittel | CO₂ (g/km) | Basis |
|---|---|---|
| **Pkw (Benzin/Diesel)** | 152 g/km | UBA 2024, Pkw-Flottendurchschnitt Deutschland |
| **ÖPNV (Mischfaktor)** | 55 g/km | UBA 2024, gewichteter Bus+Bahn-Durchschnitt |
| **Fahrrad** | 0 g/km | Keine Direktemissionen |
| **Fußweg** | 0 g/km | Keine Direktemissionen |

**Aufgeschlüsselte ÖPNV-Werte nach Fahrzeugtyp** (aus GTFS `route_type`):

| Typ | GTFS-Code | CO₂ (g/km) |
|---|---|---|
| Straßenbahn / Tram | 0 | 40 g/km |
| U-Bahn | 1 | 30 g/km |
| Bahn / Rail | 2 | 35 g/km |
| Bus | 3 | 80 g/km |

### CO₂-Berechnung pro Route

```python
# Auto
co2_auto = distanz_km × 1,4 (Detour) × 152 g/km

# ÖPNV-Anteil (P+R, B+R, A+ÖV)
co2_transit = transit_km × 55 g/km

# Gesamtemission P+R
co2_pr = co2_auto_bis_station + co2_transit
```

### CO₂-Einsparung & Jahreswirkung

- **Einsparung pro Fahrt:** `CO₂_Auto − CO₂_Alternative`
- **Jahreswirkung:** `Einsparung × 2 (Hin+Rück) × 220 Arbeitstage`
- **Äquivalenzdarstellung:** z. B. „875× Smartphone laden · 102 Tassen Kaffee"
  (Referenzwert: 1 Smartphone-Ladung ≈ 7 g CO₂)

### CO₂-Vergleich im UI

Das Balkendiagramm zeigt alle Modi relativ zum Auto (= 100 % Referenz).
Jede Alternative erhält einen prozentualen Einsparbetrag (z. B. „−64 %").

---

## 6. Wetter-Integration

- **Quelle:** Open-Meteo API (kostenlos, kein API-Key)
- **Abfrage:** Stündliche Vorhersage für Start- und Zielkoordinaten zur Ankunftszeit
- **Verwendete Parameter:**
  - Temperatur (°C)
  - Niederschlag (mm)
  - Wolkenbedeckung (%)
  - Wetterlage (Sonnig, Bewölkt, Regen, Schnee, Gewitter)

**Einfluss auf Scoring:**
- Fahrrad: Penalty bei Temperatur < Komfortgrenze oder Niederschlag
- Fußweg: Penalty bei Kälte oder Regen
- ÖPNV/Auto: Keine Wetter-Penalty (überdachte Modi)

---

## 7. Datenquellen (Übersicht)

| Quelle | Daten | Lizenz |
|---|---|---|
| [MobiData BW](https://www.mobidata-bw.de/) | GTFS-Fahrplandaten BW, P+R-Stationen | Open Data |
| [UBA 2024](https://www.umweltbundesamt.de/) | CO₂-Emissionsfaktoren Personenverkehr | Öffentlich |
| [Open-Meteo](https://open-meteo.com/) | Wetterdaten (stündlich, kostenlos) | Open Data |
| [OSRM](https://project-osrm.org/) | Autorouten-Geometrien | Open Source |
| [Nominatim/OSM](https://nominatim.org/) | Adress-Geocoding | ODbL |
