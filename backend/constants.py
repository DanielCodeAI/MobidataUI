"""
Zentrale Konstanten für MobiDataUnified.
Harmonisiert aus mobidata4-exe (Projekt A) und Mobidata (Projekt B).
"""

# ─── CO₂-Emissionen (g/km) ───────────────────────────────────────────────────
# Quellen: UBA 2024 "Emissionsdaten Personenverkehr"

CO2_CAR_G_PER_KM = 152.0        # Pkw (Projekt B, UBA 2024)
CO2_TRANSIT_G_PER_KM = 55.0     # ÖPNV Mischfaktor (Projekt B, UBA 2024)
CO2_BIKE_G_PER_KM = 0.0
CO2_WALK_G_PER_KM = 0.0

# Aufgeschlüsselte ÖPNV-Emissionen nach Verkehrsmittel (Projekt A)
# Schlüssel = GTFS route_type
CO2_TRANSIT_BY_MODE = {
    "0": 40.0,   # Tram / Straßenbahn
    "1": 30.0,   # U-Bahn / Metro
    "2": 35.0,   # Bahn / Rail
    "3": 80.0,   # Bus
    "default": 50.0,
}

# ─── Fahrgeschwindigkeiten & Detour-Indizes ──────────────────────────────────

WALK_SPEED_KMH = 4.5
BIKE_SPEED_KMH = 15.0
CAR_SPEED_KMH = 50.0       # Stadtdurchschnitt (für Fallback ohne OSRM)

DETOUR_INDEX_CAR = 1.4     # Projekt B
DETOUR_INDEX_BIKE = 1.3    # Projekt B
DETOUR_INDEX_CAR_A = 1.22  # Projekt A (konservativerer Wert)

# ─── Transfer-Penalties (Minuten) ────────────────────────────────────────────

TRANSFER_PENALTY_DEFAULT_MIN = 10   # Projekt B Basis
TRANSFER_PENALTY_RAIL_MIN = 12      # Projekt A: Rail-Umstieg teurer
TRANSFER_PENALTY_BUS_MIN = 7        # Projekt A: Bus-Umstieg günstiger
FREE_PLATFORM_TRANSFER_MIN = 1      # Projekt B: gleicher Bahnhof, anderer Bahnsteig

# ─── Routing-Kandidaten-Konfigurationen (Projekt A) ─────────────────────────
# Jede Konfiguration = ein paralleler Routing-Lauf, bestes Ergebnis gewinnt

CANDIDATE_CONFIGS = [
    {"name": "transfer_strict",  "algorithm": "dijkstra", "time_vs_co2": 0.10, "transfer_penalty": 24},
    {"name": "transfer_medium",  "algorithm": "dijkstra", "time_vs_co2": 0.18, "transfer_penalty": 18},
    {"name": "balanced",         "algorithm": "dijkstra", "time_vs_co2": 0.45, "transfer_penalty": 10},
    {"name": "fast",             "algorithm": "astar",    "time_vs_co2": 0.05, "transfer_penalty": 8},
    {"name": "eco",              "algorithm": "dijkstra", "time_vs_co2": 0.90, "transfer_penalty": 10},
]

# ─── Score-Sensitivity-Gewichtungen (Projekt B) ──────────────────────────────

SCORE_SENSITIVITY_WEIGHTS = [
    {"co2": 0.4,  "time": 0.35, "cost": 0.25, "label": "Default"},
    {"co2": 0.6,  "time": 0.2,  "cost": 0.2,  "label": "Umwelt-Fokus"},
    {"co2": 0.2,  "time": 0.6,  "cost": 0.2,  "label": "Zeit-Fokus"},
    {"co2": 0.2,  "time": 0.2,  "cost": 0.6,  "label": "Kosten-Fokus"},
    {"co2": 0.33, "time": 0.33, "cost": 0.34, "label": "Gleichgewicht"},
    {"co2": 0.8,  "time": 0.1,  "cost": 0.1,  "label": "Stark Umwelt"},
    {"co2": 0.1,  "time": 0.8,  "cost": 0.1,  "label": "Stark Zeit"},
    {"co2": 0.1,  "time": 0.1,  "cost": 0.8,  "label": "Stark Kosten"},
    {"co2": 0.5,  "time": 0.5,  "cost": 0.0,  "label": "Ohne Kosten"},
    {"co2": 0.0,  "time": 0.5,  "cost": 0.5,  "label": "Ohne CO2"},
]

# ─── GTFS-Ersatzverkehr-Filter (Projekt A) ───────────────────────────────────

REPLACEMENT_KEYWORDS = [
    "SEV", "Ersatz", "Schienenersatz", "Baustellenbus",
    "Notbus", "Notverkehr", "Ersatzverkehr",
]

# ─── Kosten für Autos (EUR/km) ───────────────────────────────────────────────

COST_CAR_EUR_PER_KM = 0.30   # ADAC Betriebskosten-Durchschnitt
COST_TRANSIT_EUR_PER_KM = 0.15
COST_BIKE_EUR_PER_KM = 0.02
COST_WALK_EUR_PER_KM = 0.0

# ─── Wetter-Komfort-Schwellen ────────────────────────────────────────────────

COMFORT_BIKE_TEMP_MIN_C = 5.0   # Fahrrad ab dieser Temperatur komfortabel
COMFORT_WALK_TEMP_MIN_C = 0.0   # Fußweg ab dieser Temperatur komfortabel
