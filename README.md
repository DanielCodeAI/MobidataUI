# MobiDataUnified — Multimodales Pendler-Routing BW

Webapplikation fuer multimodales Routing in Baden-Wuerttemberg.
Bewertet Routen nach Zeit, CO2 und Kosten — mit Best-Match-Empfehlung, Wetterintegration und interaktiver Karte.

**Verfuegbare Modi:** Auto · Park & Ride · Auto + OEPNV · Bike & Ride

---

## Voraussetzungen

| Komponente | Version | Zweck |
|---|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 24+ | Neo4j Datenbank |
| [Python](https://www.python.org/downloads/) | 3.9+ | Backend |
| Browser | aktuell | Frontend |

---

## Installation der Voraussetzungen

### Docker Desktop installieren

Docker wird benoetigt, um die Neo4j-Datenbank zu starten. Einmalige Installation:

**Windows:**
1. Sicherstellen, dass Windows 10/11 (64-bit) installiert ist
2. WSL2 aktivieren — PowerShell als Administrator oeffnen und ausfuehren:
   ```powershell
   wsl --install
   ```
   Danach den PC neu starten.
3. [Docker Desktop fuer Windows](https://www.docker.com/products/docker-desktop/) herunterladen und installieren
4. Beim ersten Start: **"Use WSL 2 instead of Hyper-V"** auswaehlen (wird meist automatisch empfohlen)
5. Pruefung — neues Terminal oeffnen:
   ```powershell
   docker --version
   ```
   Erwartete Ausgabe: `Docker version 24.x.x`

**macOS:**
1. [Docker Desktop fuer Mac](https://www.docker.com/products/docker-desktop/) herunterladen
   - Apple Silicon (M1/M2/M3): `Mac with Apple Chip` auswaehlen
   - Intel Mac: `Mac with Intel Chip` auswaehlen
2. `.dmg` oeffnen und Docker in den Applications-Ordner ziehen
3. Docker starten (erscheint als Wal-Symbol in der Menubar)
4. Pruefung im Terminal:
   ```bash
   docker --version
   ```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# Neu einloggen, damit Gruppe aktiv wird
```

---

### Python installieren

**Windows:**
1. [Python herunterladen](https://www.python.org/downloads/) (Version 3.9 oder neuer)
2. Installer starten — wichtig: Haken bei **"Add Python to PATH"** setzen
3. Pruefung:
   ```powershell
   python --version
   ```

**macOS:**
```bash
# Mit Homebrew (empfohlen):
brew install python3

# Oder direkt von python.org herunterladen
```

**Linux:**
```bash
sudo apt install -y python3 python3-pip python3-venv
```

---

### Git installieren (fuer `git clone`)

**Windows:** [Git fuer Windows](https://git-scm.com/download/win) herunterladen und installieren

**macOS:**
```bash
brew install git
# oder: xcode-select --install
```

**Linux:**
```bash
sudo apt install -y git
```

---

## Schnellstart

### 1. Repository klonen

```bash
git clone https://github.com/DanielCodeAI/MobidataUI.git
cd MobidataUI
```

### 2. Neo4j starten (Docker)

```bash
cd docker
docker compose up -d
```

Warten bis Neo4j healthy ist (~30 Sekunden):
```bash
docker ps   # Status sollte "(healthy)" zeigen
```

### 3. Virtuelle Umgebung & Dependencies

**macOS / Linux:**
```bash
cd ../backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
cd ..\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Windows (CMD):**
```cmd
cd ..\backend
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 4. GTFS-Daten in Neo4j importieren

Einmalig beim ersten Start — importiert die BW-Fahrplandaten:

```bash
# macOS / Linux
python import_gtfs.py --gtfs-path ../data/gtfs

# Windows
python import_gtfs.py --gtfs-path ..\data\gtfs
```

> Die GTFS-Daten (~779 MB) koennen von [MobiData BW](https://www.mobidata-bw.de/) heruntergeladen werden.
> Datei entpacken nach `data/gtfs/`.

### 5. Backend starten

**macOS / Linux:**
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

**Windows (PowerShell oder CMD):**
```powershell
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 6. App im Browser oeffnen

```
http://localhost:8000
```

---

## Projektstruktur

```
MobidataUI/
├── backend/
│   ├── app.py                  # FastAPI — alle Endpoints
│   ├── routing.py              # Routing-Algorithmen (A*, Dijkstra, Greedy) + Neo4j
│   ├── gtfs_processor.py       # GTFS-Filter, SEV-Erkennung, Stop-Normalisierung
│   ├── best_match_engine.py    # MAUT-Bewertungsengine (Multi-Kriterien)
│   ├── weather.py              # Wetter-Integration (Open-Meteo)
│   ├── constants.py            # CO2-Werte, Geschwindigkeiten, Penalties
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html              # Leaflet-Karte + Sidebar + Praeferenzen
├── data/
│   ├── park_ride.json          # P+R-Stationen
│   ├── bike_ride.json          # B+R-Abstellanlagen
│   └── gtfs/                   # GTFS-Daten (separat herunterladen, s.o.)
└── docker/
    └── docker-compose.yml      # Neo4j Container
```

---

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `POST` | `/route` | Multimodales Routing + Best-Match |
| `GET` | `/preferences` | Nutzer-Praeferenzen laden |
| `POST` | `/preferences` | Nutzer-Praeferenzen speichern |
| `GET` | `/api/stops/search?q=` | Haltestellen-Autocomplete |
| `GET` | `/benchmark?n=100` | Algorithmen-Vergleich |
| `GET` | `/score-sensitivity` | Score mit 10 Gewichtungsvarianten |
| `GET` | `/stops` | Alle Haltestellen (fuer Karte) |
| `GET` | `/parking` | P+R und B+R Stationen |
| `GET` | `/health` | Status-Check |

---

## Features

### Best-Match-Engine (MAUT)
Bewertet alle Routen nach einem Multi-Attribute-Utility-Modell:
- **Zeit-Score** — Reisezeit im Vergleich zu den Alternativen
- **CO2-Score** — Emissionen (UBA 2024: 152 g/km Auto, 55 g/km OEPNV)
- **Komfort-Score** — Umstiege, Distanzkomfortzonen
- **Wetter-Score** — Temperatur, Niederschlag, ueberdachte Modi
- **Praeferenz-Score** — Aktivierte/deaktivierte Verkehrsmittel

### Routing-Algorithmen

| Algorithmus | Beschreibung |
|---|---|
| **A\*** | Standard — schnell & optimal (Haversine-Heuristik) |
| **Dijkstra** | Referenz — exakt optimal |
| **Greedy** | Baseline — keine Optimierung |

### Wetter-Integration
Stuendliche Vorhersagen von [Open-Meteo](https://open-meteo.com/) (kein API-Key noetig).
Beeinflusst Fahrrad- und Fussweg-Bewertung automatisch.

---

## Konfiguration

Umgebungsvariablen fuer das Backend (`.env` Datei oder direkt setzen):

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=mobidata2024
```

---

## Datenquellen

| Quelle | Daten |
|---|---|
| [MobiData BW](https://www.mobidata-bw.de/) | GTFS-Fahrplandaten, P+R-Stationen |
| [Open-Meteo](https://open-meteo.com/) | Wetter (kostenlos, kein API-Key) |
| [UBA 2024](https://www.umweltbundesamt.de/) | CO2-Emissionsfaktoren |
| [OSRM](https://project-osrm.org/) | Autorouten-Geometrien |
| [Nominatim/OSM](https://nominatim.org/) | Adress-Geocoding |

---

## Troubleshooting

**`uvicorn: command not found`**
→ Virtuelle Umgebung aktivieren (Schritt 3 wiederholen)

**`OEPNV-Daten nicht verfuegbar`**
→ Neo4j laeuft nicht oder GTFS wurde noch nicht importiert

**Windows: `Activate.ps1 cannot be loaded`**
→ PowerShell als Administrator oeffnen und einmalig ausfuehren:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Docker: `port 7687 already in use`**
→ Anderer Neo4j-Container laeuft bereits — `docker ps` pruefen und ggf. stoppen
