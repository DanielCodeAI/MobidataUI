"""
app.py — FastAPI Backend für MobiDataUnified.

Vereint:
- Projekt B (Mobidata): FastAPI, Neo4j, multimodales Routing (P+R, B+R), OSRM, Leaflet
- Projekt A (mobidata4-exe): Best-Match-Engine, Wetter-Integration, Nutzer-Präferenzen (SQLite)

Endpoints:
  POST /route              — Multimodales Routing + Best-Match
  GET  /preferences        — Präferenzen laden
  POST /preferences        — Präferenzen speichern
  GET  /api/stops/search   — Stop-Autocomplete
  GET  /benchmark          — Algorithmen-Vergleich
  GET  /score-sensitivity  — Score mit 10 Gewichtungskombinationen
  GET  /stops              — Alle Haltestellen (Karte)
  GET  /parking            — P+R / B+R Stationen
  GET  /health             — Health-Check

Starten: uvicorn app:app --reload --port 8000
"""

import json
import logging
import os
import random
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from routing import (
    TransitGraph, run_all_algorithms, run_algorithm,
)
from best_match_engine import build_best_match_result
from weather import fetch_weather_for_coordinates
from gtfs_processor import haversine_km, normalize_text, simplify_stop_name_for_display, alias_tokens
from constants import (
    CO2_CAR_G_PER_KM, CO2_TRANSIT_G_PER_KM,
    DETOUR_INDEX_CAR, DETOUR_INDEX_BIKE,
    WALK_SPEED_KMH, BIKE_SPEED_KMH,
    SCORE_SENSITIVITY_WEIGHTS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / "data"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "mobidata2024")

# Spritkosten
FUEL_PRICE_EUR_PER_L = 1.75
FUEL_CONSUMPTION_L_PER_100KM = 7.4
CAR_COST_EUR_PER_KM = FUEL_PRICE_EUR_PER_L * FUEL_CONSUMPTION_L_PER_100KM / 100
TRANSIT_COST_PER_TRIP_EUR = 2.0
BIKE_COST_PER_TRIP_EUR = 0.91

OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"

DB_PATH = DATA_DIR / "preferences.db"

# ─── Global State ─────────────────────────────────────────────────────────────

transit_graph: Optional[TransitGraph] = None
park_ride_stations: list[dict] = []
bike_ride_stations: list[dict] = []


# ─── Präferenzen (SQLite) ─────────────────────────────────────────────────────

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def _read_preferences() -> dict:
    defaults = {
        "mode_walk": True, "mode_bike": True, "mode_car": True, "mode_pt": True,
        "max_walk_km": 1.5, "max_bike_km": 10.0,
        "pref_time_vs_env": 50, "pref_comfort": 60,
        "comfort_bike_temp": 15.0, "comfort_walk_temp": 10.0,
        "prefer_covered_modes": False, "reduce_car_in_snow": False,
    }
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute("SELECT key, value FROM preferences").fetchall()
        con.close()
        for key, value in rows:
            try:
                defaults[key] = json.loads(value)
            except json.JSONDecodeError:
                defaults[key] = value
    except Exception:
        pass
    return defaults


def _write_preferences(prefs: dict):
    con = sqlite3.connect(DB_PATH)
    for key, value in prefs.items():
        con.execute(
            "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
            (key, json.dumps(value))
        )
    con.commit()
    con.close()


# ─── Startup ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transit_graph, park_ride_stations, bike_ride_stations
    _init_db()
    log.info("Lade Transit-Graph aus Neo4j...")
    try:
        transit_graph = TransitGraph()
        transit_graph.load_from_neo4j()
        log.info("Graph geladen: %d Haltestellen, %d Verbindungen.",
                 transit_graph.n_stops, transit_graph.n_connections)
    except Exception as e:
        log.error("Fehler beim Laden des Graphen: %s", e)
        log.warning("ÖPNV-Routing nicht verfügbar.")
        transit_graph = None

    pr_path = DATA_DIR / "park_ride.json"
    br_path = DATA_DIR / "bike_ride.json"
    if pr_path.exists():
        park_ride_stations = json.loads(pr_path.read_text(encoding="utf-8"))
        log.info("%d P+R-Stationen geladen.", len(park_ride_stations))
    if br_path.exists():
        bike_ride_stations = json.loads(br_path.read_text(encoding="utf-8"))
        log.info("%d B+R-Stationen geladen.", len(bike_ride_stations))

    yield


app = FastAPI(title="MobiDataUnified", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

async def geocode(address: str) -> Optional[tuple]:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(NOMINATIM_BASE, params={
                "q": address, "format": "json", "limit": 1, "countrycodes": "de,ch",
            }, headers={"User-Agent": "MobiDataUnified/2.0"}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            log.warning("Geocoding fehlgeschlagen für '%s': %s", address, e)
    return None


async def osrm_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    url = f"{OSRM_BASE}/{lon1},{lat1};{lon2},{lat2}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "Ok" and data.get("routes"):
                r = data["routes"][0]
                return {
                    "distance_km": round(r["distance"] / 1000, 2),
                    "duration_min": round(r["duration"] / 60, 1),
                    "geometry": r.get("geometry"),
                    "estimated": False,
                }
        except Exception as e:
            log.warning("OSRM fehlgeschlagen: %s", e)
    # Haversine-Fallback
    dist_km = haversine_km(lat1, lon1, lat2, lon2) * DETOUR_INDEX_CAR
    return {
        "distance_km": round(dist_km, 2),
        "duration_min": round(dist_km, 1),
        "geometry": None,
        "estimated": True,
    }


def find_nearest_stop(lat: float, lon: float, max_km: float = 1.5) -> Optional[dict]:
    if not transit_graph:
        return None
    best, best_dist = None, max_km
    for sid, (slat, slon) in transit_graph.stop_coords.items():
        d = haversine_km(lat, lon, slat, slon)
        if d < best_dist:
            best_dist = d
            best = {"stop_id": sid, "name": transit_graph.stop_names[sid],
                    "lat": slat, "lon": slon, "distance_km": round(d, 3)}
    return best


def _find_stop_near(lat: float, lon: float, max_m: float) -> Optional[dict]:
    return find_nearest_stop(lat, lon, max_km=max_m / 1000)


def find_nearest_stations(lat: float, lon: float, stations: list[dict],
                          max_km: float, limit: int = 5) -> list[dict]:
    results = []
    for s in stations:
        dist = haversine_km(lat, lon, s["lat"], s["lon"])
        if dist <= max_km:
            results.append({**s, "distance_km": round(dist, 2)})
    results.sort(key=lambda x: x["distance_km"])
    return results[:limit]


def compute_pendler_score(co2_car, co2_alt, time_car, time_alt,
                          cost_car, cost_alt,
                          w_co2=0.4, w_time=0.35, w_cost=0.25) -> float:
    co2_score = max(0, min(100, (co2_car - co2_alt) / co2_car * 100)) if co2_car > 0 else 50
    time_ratio = time_alt / time_car if time_car > 0 else 1
    time_score = max(0, min(100, (2 - time_ratio) / 2 * 100))
    cost_score = max(0, min(100, (cost_car - cost_alt) / cost_car * 100)) if cost_car > 0 else 50
    total = w_co2 * co2_score + w_time * time_score + w_cost * cost_score
    w_sum = w_co2 + w_time + w_cost
    return round(max(0, min(100, total / w_sum if w_sum > 0 else total)), 1)


def time_str_to_minutes(t: str) -> int:
    parts = t.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_str(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _transit_km_from_path(path: list[dict]) -> float:
    km = 0.0
    for i in range(len(path) - 1):
        c1 = transit_graph.stop_coords.get(path[i]["stop_id"])
        c2 = transit_graph.stop_coords.get(path[i + 1]["stop_id"])
        if c1 and c2:
            km += haversine_km(c1[0], c1[1], c2[0], c2[1])
    return km


# ─── Request Models ───────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    start_address: Optional[str] = None
    end_address: Optional[str] = None
    arrival_time: str = "08:30"
    travel_date: str = Field(default="", description="Reisedatum YYYY-MM-DD, leer = heute")
    weight_co2: float = Field(default=0.4, ge=0, le=1)
    weight_time: float = Field(default=0.35, ge=0, le=1)
    weight_cost: float = Field(default=0.25, ge=0, le=1)
    max_bike_km: float = Field(default=5.0, ge=0, le=30)
    max_walk_m: float = Field(default=800.0, ge=0, le=3000)
    algorithm: str = Field(default="astar", description="astar | dijkstra | greedy")
    # Wetter-Integration (optional)
    fetch_weather: bool = Field(default=True, description="Wetter für Start/Ziel abrufen")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"error": "index.html not found"}, status_code=404)


@app.get("/health")
async def health():
    graph_ok = transit_graph is not None and transit_graph.n_stops > 0
    return {
        "status": "ok" if graph_ok else "degraded",
        "graph_loaded": graph_ok,
        "stops": transit_graph.n_stops if transit_graph else 0,
        "connections": transit_graph.n_connections if transit_graph else 0,
        "park_ride_stations": len(park_ride_stations),
        "bike_ride_stations": len(bike_ride_stations),
    }


@app.get("/preferences")
async def get_preferences():
    return _read_preferences()


@app.post("/preferences")
async def save_preferences(prefs: dict):
    _write_preferences(prefs)
    return {"status": "ok"}


@app.get("/api/stops/search")
async def search_stops(q: str = Query(default="", min_length=1)):
    """Stop-Autocomplete mit Fuzzy-Matching (aus Projekt A)."""
    if not transit_graph or not q:
        return []

    query_norm = normalize_text(q)
    query_alias = alias_tokens(query_norm)

    results = []
    seen_display = set()

    for sid, name in transit_graph.stop_names.items():
        display = simplify_stop_name_for_display(name)
        if display in seen_display:
            continue

        name_norm = normalize_text(display)
        score = 0

        if query_norm == name_norm:
            score = 300
        elif name_norm.startswith(query_norm):
            score = 170
        elif query_norm in name_norm:
            score = 130
        elif any(tok in name_norm for tok in query_alias.split()):
            score = 80

        if score > 0:
            seen_display.add(display)
            coords = transit_graph.stop_coords.get(sid, (None, None))
            results.append({
                "stop_id": sid,
                "name": display,
                "lat": coords[0],
                "lon": coords[1],
                "score": score,
            })

    results.sort(key=lambda x: -x["score"])
    return results[:20]


@app.post("/route")
async def compute_route(req: RouteRequest):
    """
    Hauptrouten-Endpoint.
    Berechnet: Auto, P+R, Auto+ÖPNV, B+R
    + Best-Match-Engine (MAUT aus Projekt A)
    + Wetter-Integration
    """
    # Koordinaten auflösen
    start_lat, start_lon = req.start_lat, req.start_lon
    end_lat, end_lon = req.end_lat, req.end_lon

    if start_lat is None and req.start_address:
        coords = await geocode(req.start_address)
        if not coords:
            raise HTTPException(400, f"Startadresse nicht gefunden: {req.start_address}")
        start_lat, start_lon = coords

    if end_lat is None and req.end_address:
        coords = await geocode(req.end_address)
        if not coords:
            raise HTTPException(400, f"Zieladresse nicht gefunden: {req.end_address}")
        end_lat, end_lon = coords

    if start_lat is None or end_lat is None:
        raise HTTPException(400, "Start- und Zielkoordinaten oder Adressen erforderlich.")

    arrival_min = time_str_to_minutes(req.arrival_time)
    preferences = _read_preferences()

    # Wetter abrufen (Projekt A)
    weather_origin, weather_destination = None, None
    if req.fetch_weather:
        try:
            when = datetime.now().replace(hour=arrival_min // 60, minute=arrival_min % 60)
            weather_origin = fetch_weather_for_coordinates(start_lat, start_lon, when)
            weather_destination = fetch_weather_for_coordinates(end_lat, end_lon, when)
        except Exception as e:
            log.warning("Wetter-Abruf fehlgeschlagen: %s", e)

    # ═══ Auto (Baseline) ═══
    car = await osrm_route(start_lat, start_lon, end_lat, end_lon)
    car_co2 = car["distance_km"] * CO2_CAR_G_PER_KM
    car_cost = car["distance_km"] * CAR_COST_EUR_PER_KM
    car_only = {
        "name": "Auto",
        "total_time_min": car["duration_min"],
        "distance_km": car["distance_km"],
        "co2_g": round(car_co2),
        "cost_eur": round(car_cost, 2),
        "geometry": car.get("geometry"),
        "estimated": car["estimated"],
        "is_pt": False,
        "show_transfers": False,
    }

    # ═══ P+R ═══
    park_and_ride, pr_reason = None, None
    nearest_pr = find_nearest_stations(start_lat, start_lon, park_ride_stations, max_km=30, limit=3)
    if not nearest_pr:
        pr_reason = "Keine P+R-Station im Umkreis von 30 km."
    elif not transit_graph:
        pr_reason = "ÖPNV-Daten nicht verfügbar."
    else:
        park_and_ride = await _compute_pr_route(
            start_lat, start_lon, end_lat, end_lon,
            nearest_pr, arrival_min, car_only, req,
        )
        if park_and_ride is None:
            pr_reason = "Keine ÖPNV-Verbindung im Zeitfenster gefunden."

    # ═══ Auto + ÖPNV ═══
    auto_transit, at_reason = None, None
    if not transit_graph:
        at_reason = "ÖPNV-Daten nicht verfügbar."
    else:
        auto_transit = await _compute_auto_transit_route(
            start_lat, start_lon, end_lat, end_lon,
            arrival_min, car_only, req,
        )
        if auto_transit is None:
            at_reason = "Keine ÖPNV-Verbindung gefunden."

    # ═══ B+R ═══
    bike_and_ride, br_reason = None, None
    nearest_br = find_nearest_stations(start_lat, start_lon, bike_ride_stations,
                                       max_km=req.max_bike_km, limit=3)
    if not nearest_br:
        br_reason = "Keine B+R-Anlage im Umkreis."
    elif not transit_graph:
        br_reason = "ÖPNV-Daten nicht verfügbar."
    else:
        bike_and_ride = await _compute_br_route(
            start_lat, start_lon, end_lat, end_lon,
            nearest_br, arrival_min, car_only, req,
        )
        if bike_and_ride is None:
            br_reason = "Keine ÖPNV-Verbindung gefunden."

    # ═══ Best-Match (Projekt A MAUT-Engine) ═══
    comparison_modes = [m for m in [car_only, park_and_ride, auto_transit, bike_and_ride] if m]
    best_match_result = build_best_match_result(
        comparison_modes=comparison_modes,
        preferences=preferences,
        weather_origin=weather_origin,
        weather_destination=weather_destination,
    )

    from datetime import date as _date
    travel_date = req.travel_date if req.travel_date else _date.today().isoformat()

    return {
        "car_only": car_only,
        "park_and_ride": park_and_ride,
        "auto_transit": auto_transit,
        "bike_and_ride": bike_and_ride,
        "co2_saved_pr_g": round(car_co2 - park_and_ride["co2_g"]) if park_and_ride else None,
        "co2_saved_at_g": round(car_co2 - auto_transit["co2_g"]) if auto_transit else None,
        "co2_saved_br_g": round(car_co2 - bike_and_ride["co2_g"]) if bike_and_ride else None,
        "reason_pr": pr_reason,
        "reason_at": at_reason,
        "reason_br": br_reason,
        "best_match": best_match_result,
        "travel_date": travel_date,
        "arrival_time": req.arrival_time,
        "weather_origin": weather_origin,
        "weather_destination": weather_destination,
    }


# ─── Routing-Helfer ───────────────────────────────────────────────────────────

async def _compute_pr_route(start_lat, start_lon, end_lat, end_lon,
                             nearest_pr, arrival_min, car_only, req) -> Optional[dict]:
    for pr in nearest_pr:
        car_seg = await osrm_route(start_lat, start_lon, pr["lat"], pr["lon"])
        entry_stop = _find_stop_near(pr["lat"], pr["lon"], max_m=req.max_walk_m)
        if not entry_stop:
            continue
        exit_stop = find_nearest_stop(end_lat, end_lon, max_km=req.max_walk_m / 1000)
        if not exit_stop:
            continue

        walk_to_dest_min = exit_stop["distance_km"] / WALK_SPEED_KMH * 60
        walk_to_stop_min = entry_stop["distance_km"] / WALK_SPEED_KMH * 60
        earliest_depart = max(0, int(arrival_min - 120))
        algo = req.algorithm if req.algorithm in ("astar", "dijkstra", "greedy") else "astar"

        result = run_algorithm(transit_graph, entry_stop["stop_id"], exit_stop["stop_id"],
                               earliest_depart, algo)
        algo_results = run_all_algorithms(transit_graph, entry_stop["stop_id"],
                                          exit_stop["stop_id"], earliest_depart)
        if not result or not result.found:
            continue

        transit_km = _transit_km_from_path(result.path)
        auto_km = car_seg["distance_km"]
        total_duration = (car_seg["duration_min"] + walk_to_stop_min +
                          result.total_duration_min + walk_to_dest_min)
        co2 = auto_km * CO2_CAR_G_PER_KM + transit_km * CO2_TRANSIT_G_PER_KM
        cost = auto_km * CAR_COST_EUR_PER_KM + TRANSIT_COST_PER_TRIP_EUR

        return {
            "name": "Park & Ride",
            "total_time_min": round(total_duration, 1),
            "distance_km": round(auto_km + transit_km, 2),
            "co2_g": round(co2),
            "cost_eur": round(cost, 2),
            "is_pt": True,
            "show_transfers": True,
            "transfers": result.num_transfers,
            "score": compute_pendler_score(
                car_only["co2_g"], co2, car_only["total_time_min"], total_duration,
                car_only["cost_eur"], cost, req.weight_co2, req.weight_time, req.weight_cost,
            ),
            "segments": [
                {"type": "car", "from": "Start", "to": pr["name"],
                 "distance_km": auto_km, "duration_min": round(car_seg["duration_min"], 1),
                 "geometry": car_seg.get("geometry")},
                {"type": "walk", "from": pr["name"], "to": entry_stop["name"],
                 "distance_m": round(entry_stop["distance_km"] * 1000),
                 "duration_min": round(walk_to_stop_min, 1)},
                {"type": "transit", "from": entry_stop["name"], "to": exit_stop["name"],
                 "distance_km": round(transit_km, 2),
                 "duration_min": result.total_duration_min,
                 "path": result.path},
                {"type": "walk", "from": exit_stop["name"], "to": "Ziel",
                 "distance_m": round(exit_stop["distance_km"] * 1000),
                 "duration_min": round(walk_to_dest_min, 1)},
            ],
            "parking_station": {"name": pr["name"], "lat": pr["lat"], "lon": pr["lon"],
                                 "available": pr.get("available"),
                                 "has_realtime": pr.get("has_realtime", False)},
            "algorithm_results": {k: v.to_dict() for k, v in algo_results.items()},
        }
    return None


async def _compute_auto_transit_route(start_lat, start_lon, end_lat, end_lon,
                                       arrival_min, car_only, req) -> Optional[dict]:
    candidates = sorted(
        [(sid, slat, slon, haversine_km(start_lat, start_lon, slat, slon))
         for sid, (slat, slon) in transit_graph.stop_coords.items()
         if haversine_km(start_lat, start_lon, slat, slon) <= 15],
        key=lambda x: x[3]
    )[:8]
    if not candidates:
        return None

    exit_stop = find_nearest_stop(end_lat, end_lon, max_km=req.max_walk_m / 1000)
    if not exit_stop:
        return None

    walk_to_dest_min = exit_stop["distance_km"] / WALK_SPEED_KMH * 60
    earliest_depart = max(0, int(arrival_min - 120))
    algo = req.algorithm if req.algorithm in ("astar", "dijkstra", "greedy") else "astar"

    for sid, slat, slon, _ in candidates:
        car_seg = await osrm_route(start_lat, start_lon, slat, slon)
        result = run_algorithm(transit_graph, sid, exit_stop["stop_id"], earliest_depart, algo)
        algo_results = run_all_algorithms(transit_graph, sid, exit_stop["stop_id"], earliest_depart)
        if not result or not result.found:
            continue

        transit_km = _transit_km_from_path(result.path)
        auto_km = car_seg["distance_km"]
        total_duration = car_seg["duration_min"] + result.total_duration_min + walk_to_dest_min
        co2 = auto_km * CO2_CAR_G_PER_KM + transit_km * CO2_TRANSIT_G_PER_KM
        cost = auto_km * CAR_COST_EUR_PER_KM + TRANSIT_COST_PER_TRIP_EUR
        stop_name = transit_graph.stop_names.get(sid, "Haltestelle")

        return {
            "name": "Auto + ÖPNV",
            "total_time_min": round(total_duration, 1),
            "distance_km": round(auto_km + transit_km, 2),
            "co2_g": round(co2),
            "cost_eur": round(cost, 2),
            "is_pt": True,
            "show_transfers": True,
            "transfers": result.num_transfers,
            "score": compute_pendler_score(
                car_only["co2_g"], co2, car_only["total_time_min"], total_duration,
                car_only["cost_eur"], cost, req.weight_co2, req.weight_time, req.weight_cost,
            ),
            "segments": [
                {"type": "car", "from": "Start", "to": stop_name,
                 "distance_km": auto_km, "duration_min": round(car_seg["duration_min"], 1),
                 "geometry": car_seg.get("geometry")},
                {"type": "transit", "from": stop_name, "to": exit_stop["name"],
                 "distance_km": round(transit_km, 2),
                 "duration_min": result.total_duration_min,
                 "path": result.path},
                {"type": "walk", "from": exit_stop["name"], "to": "Ziel",
                 "distance_m": round(exit_stop["distance_km"] * 1000),
                 "duration_min": round(walk_to_dest_min, 1)},
            ],
            "entry_stop": {"name": stop_name, "lat": slat, "lon": slon},
            "algorithm_results": {k: v.to_dict() for k, v in algo_results.items()},
        }
    return None


async def _compute_br_route(start_lat, start_lon, end_lat, end_lon,
                             nearest_br, arrival_min, car_only, req) -> Optional[dict]:
    for br in nearest_br:
        bike_dist_km = haversine_km(start_lat, start_lon, br["lat"], br["lon"]) * DETOUR_INDEX_BIKE
        bike_time_min = bike_dist_km / BIKE_SPEED_KMH * 60

        entry_stop = _find_stop_near(br["lat"], br["lon"], max_m=min(req.max_walk_m, 500))
        if not entry_stop:
            continue
        exit_stop = find_nearest_stop(end_lat, end_lon, max_km=req.max_walk_m / 1000)
        if not exit_stop:
            continue

        walk_to_dest_min = exit_stop["distance_km"] / WALK_SPEED_KMH * 60
        walk_to_stop_min = entry_stop["distance_km"] / WALK_SPEED_KMH * 60
        earliest_depart = max(0, int(arrival_min - 120))
        algo = req.algorithm if req.algorithm in ("astar", "dijkstra", "greedy") else "astar"

        result = run_algorithm(transit_graph, entry_stop["stop_id"], exit_stop["stop_id"],
                               earliest_depart, algo)
        algo_results = run_all_algorithms(transit_graph, entry_stop["stop_id"],
                                          exit_stop["stop_id"], earliest_depart)
        if not result or not result.found:
            continue

        transit_km = _transit_km_from_path(result.path)
        total_duration = (bike_time_min + walk_to_stop_min +
                          result.total_duration_min + walk_to_dest_min)
        co2 = transit_km * CO2_TRANSIT_G_PER_KM
        cost = BIKE_COST_PER_TRIP_EUR + TRANSIT_COST_PER_TRIP_EUR

        return {
            "name": "Bike & Ride",
            "total_time_min": round(total_duration, 1),
            "distance_km": round(bike_dist_km + transit_km, 2),
            "co2_g": round(co2),
            "cost_eur": round(cost, 2),
            "is_pt": True,
            "show_transfers": True,
            "transfers": result.num_transfers,
            "score": compute_pendler_score(
                car_only["co2_g"], co2, car_only["total_time_min"], total_duration,
                car_only["cost_eur"], cost, req.weight_co2, req.weight_time, req.weight_cost,
            ),
            "segments": [
                {"type": "bike", "from": "Start", "to": br["name"],
                 "distance_km": round(bike_dist_km, 2), "duration_min": round(bike_time_min, 1)},
                {"type": "walk", "from": br["name"], "to": entry_stop["name"],
                 "distance_m": round(entry_stop["distance_km"] * 1000),
                 "duration_min": round(walk_to_stop_min, 1)},
                {"type": "transit", "from": entry_stop["name"], "to": exit_stop["name"],
                 "distance_km": round(transit_km, 2),
                 "duration_min": result.total_duration_min,
                 "path": result.path},
                {"type": "walk", "from": exit_stop["name"], "to": "Ziel",
                 "distance_m": round(exit_stop["distance_km"] * 1000),
                 "duration_min": round(walk_to_dest_min, 1)},
            ],
            "bike_station": {"name": br["name"], "lat": br["lat"], "lon": br["lon"],
                             "type": br.get("type", ""), "capacity": br.get("capacity", 0)},
            "algorithm_results": {k: v.to_dict() for k, v in algo_results.items()},
        }
    return None


# ─── Weitere Endpoints ────────────────────────────────────────────────────────

@app.get("/benchmark")
async def benchmark(n: int = Query(default=100, ge=10, le=1000)):
    if not transit_graph or transit_graph.n_stops < 2:
        raise HTTPException(503, "Transit-Graph nicht geladen.")

    stop_ids = list(transit_graph.stop_coords.keys())
    departure_times = [420, 450, 480, 510, 540]
    results_by_algo: dict[str, list[dict]] = {"greedy": [], "dijkstra": [], "astar": []}

    for _ in range(n):
        s1, s2 = random.sample(stop_ids, 2)
        dep = random.choice(departure_times)
        for name, result in run_all_algorithms(transit_graph, s1, s2, dep).items():
            results_by_algo[name].append({
                "runtime_ms": result.runtime_ms,
                "nodes_expanded": result.nodes_expanded,
                "cost": result.cost if result.found else None,
                "found": result.found,
            })

    summary = {}
    dijkstra_costs = {i: r["cost"] for i, r in enumerate(results_by_algo["dijkstra"]) if r["found"]}

    for algo_name, runs in results_by_algo.items():
        runtimes = sorted(r["runtime_ms"] for r in runs)
        costs = [r["cost"] for r in runs if r["found"]]
        found_count = sum(1 for r in runs if r["found"])
        optimality = [
            runs[i]["cost"] / dijkstra_costs[i]
            for i, r in enumerate(runs)
            if r["found"] and i in dijkstra_costs and dijkstra_costs[i] > 0
        ]
        summary[algo_name] = {
            "avg_runtime_ms": round(sum(runtimes) / len(runtimes), 2) if runtimes else 0,
            "p95_runtime_ms": round(runtimes[int(len(runtimes) * 0.95)], 2) if runtimes else 0,
            "avg_nodes_expanded": round(
                sum(r["nodes_expanded"] for r in runs) / len(runs), 1) if runs else 0,
            "avg_path_cost": round(sum(costs) / len(costs), 2) if costs else 0,
            "path_optimality_vs_dijkstra": round(
                sum(optimality) / len(optimality), 4) if optimality else None,
            "n_found": found_count,
            "n_not_found": len(runs) - found_count,
        }

    return {"n": n, "algorithms": summary}


@app.get("/score-sensitivity")
async def score_sensitivity(
    start_lat: float = Query(...), start_lon: float = Query(...),
    end_lat: float = Query(...), end_lon: float = Query(...),
    arrival_time: str = Query(default="08:30"),
):
    req = RouteRequest(start_lat=start_lat, start_lon=start_lon,
                       end_lat=end_lat, end_lon=end_lon,
                       arrival_time=arrival_time, fetch_weather=False)
    route_data = await compute_route(req)
    car = route_data["car_only"]
    results = []

    for wc in SCORE_SENSITIVITY_WEIGHTS:
        entry: dict[str, Any] = {"weights": wc}
        for key, mode_key in [("pr_score", "park_and_ride"), ("br_score", "bike_and_ride"),
                               ("at_score", "auto_transit")]:
            mode = route_data.get(mode_key)
            entry[key] = compute_pendler_score(
                car["co2_g"], mode["co2_g"],
                car["total_time_min"], mode["total_time_min"],
                car["cost_eur"], mode["cost_eur"],
                wc["co2"], wc["time"], wc["cost"],
            ) if mode else None
        results.append(entry)

    return {
        "route_summary": {"car_duration_min": car["total_time_min"], "car_co2_g": car["co2_g"]},
        "sensitivity": results,
    }


@app.get("/stops")
async def get_stops():
    if not transit_graph:
        return []
    return [
        {"stop_id": sid, "name": transit_graph.stop_names[sid], "lat": c[0], "lon": c[1]}
        for sid, c in transit_graph.stop_coords.items()
    ]


@app.get("/parking")
async def get_parking():
    return {"park_ride": park_ride_stations, "bike_ride": bike_ride_stations}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
