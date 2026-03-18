"""
GTFS-Verarbeitung für MobiDataUnified.
Extrahiert aus mobidata4-exe/app/routing_engine.py.

Enthält:
- Stop-Normalisierung & Aliase
- Modus-Klassifikation (classify_mode)
- Kanten-Filter (should_exclude_transit_edge)
- GTFS-Lader (load_gtfs_data)
- Kanten-Vorbereitung (_prepare_transit_edges, _prepare_transfer_edges)
"""

import os
import re
from typing import Optional

import pandas as pd
from haversine import haversine, Unit

from constants import REPLACEMENT_KEYWORDS

# ─── Konstanten ───────────────────────────────────────────────────────────────

RAIL_PREFIXES = (
    "ICE", "IC", "EC", "ECE", "RJ", "TGV", "FLX",
    "IRE", "RE", "RB", "MEX"
)

_OPTIONAL_TRANSFERS_DF: Optional[pd.DataFrame] = None

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def calc_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine((lat1, lon1), (lat2, lon2), unit=Unit.KILOMETERS)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Alias für calc_distance_km (Kompatibilität mit Projekt B)."""
    return calc_distance_km(lat1, lon1, lat2, lon2)


def parse_gtfs_time_to_minutes(value: str) -> Optional[int]:
    if pd.isna(value):
        return None
    value = str(value).strip()
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return hours * 60 + minutes + (1 if seconds >= 30 else 0)


# ─── Stop-Normalisierung ─────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    text = str(text).strip().lower()
    text = text.replace("hauptbahnhof", "hbf")
    text = text.replace("zentraler omnibusbahnhof", "zob")
    text = text.replace("omnibusbahnhof", "zob")
    text = text.replace("busbahnhof", "zob")
    text = text.replace("bstg", "bussteig")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def simplify_stop_name_for_display(name: str) -> str:
    name = str(name).strip()
    name = re.sub(r"\s*\([^)]*\)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+gleis\s*\d+[a-z]?\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+bstg\.?\s*\d+[a-z]?\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+bussteig\s*\d+[a-z]?\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\boben\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\bunten\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()


def city_from_stop_name(name: str) -> str:
    name = simplify_stop_name_for_display(name)
    parts = re.split(r"[\s,/-]+", name)
    return parts[0] if parts else name


def alias_tokens(text: str) -> str:
    t = normalize_text(text)
    if "zob" in t:
        t += " bahnhof hbf busbahnhof omnibusbahnhof"
    if "hbf" in t:
        t += " hauptbahnhof bahnhof"
    return t


# ─── Linienerkennung ─────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return str(s or "").strip().upper()


def combined_service_text(line_name: str, long_name: str = "", agency_id: str = "") -> str:
    return f"{_clean(line_name)} {_clean(long_name)} {_clean(agency_id)}".strip()


def has_replacement_keywords(line_name: str, long_name: str = "", agency_id: str = "") -> bool:
    combined = combined_service_text(line_name, long_name, agency_id)
    return any(k in combined for k in REPLACEMENT_KEYWORDS)


def is_s_bahn_label(line_name: str) -> bool:
    line = _clean(line_name)
    return bool(re.match(r"^S\s*\d+", line) or re.match(r"^S\d+", line))


def looks_like_urban_street_stop(stop_name: str) -> bool:
    name = normalize_text(simplify_stop_name_for_display(stop_name))
    streetish = ["straße", "strasse", "str.", "platz", "brücke", "brucke",
                 "gasse", "weg", "allee", "ring", "tor", "park", "schule"]
    return any(token in name for token in streetish)


def looks_like_rail_stop(stop_name: str) -> bool:
    name = normalize_text(simplify_stop_name_for_display(stop_name))
    railish = ["hbf", "bahnhof", "bf", "gleis", "bahnsteig", "db", "zob"]
    return any(token in name for token in railish)


def classify_mode(route_type: str, line_name: str, long_name: str = "", agency_id: str = "") -> str:
    """
    Strenge Modus-Klassifikation nach GTFS route_type.
    SEV/Ersatzverkehr wird immer als 'bus' klassifiziert.
    """
    rt = str(route_type or "").strip()
    line = _clean(line_name)
    longn = _clean(long_name)
    agency = _clean(agency_id)

    if rt == "transfer":
        return "transfer"

    if has_replacement_keywords(line, longn, agency):
        return "bus"

    # GTFS route_type hat Vorrang
    if rt == "3":
        return "bus"
    if rt == "0":
        return "tram"
    if rt == "1":
        return "subway"
    if rt == "2":
        return "rail"

    # Namensmuster-Fallback
    if any(line.startswith(p) for p in RAIL_PREFIXES):
        return "rail"
    if is_s_bahn_label(line):
        return "rail"
    if any(k in longn for k in ["REGIONAL-EXPRESS", "REGIOEXPRESS", "REGIONALBAHN", "INTERCITY", "S-BAHN"]):
        return "rail"
    if any(k in agency for k in ["DB", "SWEG", "AVG", "GO-AHEAD", "ABELLIO"]):
        return "rail"

    return "other"


def route_type_to_label(route_type: str, mode_class: Optional[str] = None) -> str:
    mc = mode_class or classify_mode(route_type, "")
    labels = {
        "tram": "Tram",
        "subway": "U-Bahn",
        "rail": "Bahn",
        "bus": "Bus",
        "transfer": "Umstieg",
    }
    return labels.get(mc, "ÖPNV")


# ─── Kanten-Filter ────────────────────────────────────────────────────────────

def should_exclude_transit_edge(row) -> bool:
    """Gibt True zurück wenn diese GTFS-Kante gefiltert werden soll."""
    line = row.get("route_short_name", "")
    long_name = row.get("route_long_name", "")
    agency = row.get("agency_id", "")
    route_type = str(row.get("route_type", "")).strip()
    mode_class = row.get("mode_class", "other")
    distance_km = float(row.get("distance_km", 0.0) or 0.0)
    time_min = float(row.get("time_min", 0.0) or 0.0)
    start_name = str(row.get("stop_name_start", ""))
    end_name = str(row.get("stop_name_end", ""))

    if has_replacement_keywords(line, long_name, agency):
        return True

    # Schienen-benannte Bus-Linien (SEV) ausschließen
    if route_type == "3" and (
        any(_clean(line).startswith(p) for p in RAIL_PREFIXES) or is_s_bahn_label(line)
    ):
        return True

    # Unplausible Kurz-Railkanten zu Straßenstopps
    if mode_class == "rail":
        start_streetish = looks_like_urban_street_stop(start_name)
        end_streetish = looks_like_urban_street_stop(end_name)
        start_railish = looks_like_rail_stop(start_name)
        end_railish = looks_like_rail_stop(end_name)
        if distance_km < 3.0 and time_min <= 8.0:
            if (start_streetish or end_streetish) and not (start_railish and end_railish):
                return True

    return False


# ─── GTFS-Lader ───────────────────────────────────────────────────────────────

def load_gtfs_data(data_path: str):
    """
    Lädt GTFS-Rohdaten aus CSV-Dateien.
    Gibt zurück: (stops, stop_times, trips, routes)
    """
    global _OPTIONAL_TRANSFERS_DF

    print(f"Lade GTFS-Daten aus: {data_path}")

    stops = pd.read_csv(os.path.join(data_path, "stops.txt"), dtype=str)
    stop_times = pd.read_csv(os.path.join(data_path, "stop_times.txt"), dtype=str)
    trips = pd.read_csv(os.path.join(data_path, "trips.txt"), dtype=str)
    routes = pd.read_csv(os.path.join(data_path, "routes.txt"), dtype=str)

    transfers_path = os.path.join(data_path, "transfers.txt")
    if os.path.exists(transfers_path):
        try:
            _OPTIONAL_TRANSFERS_DF = pd.read_csv(transfers_path, dtype=str)
            print("transfers.txt geladen.")
        except Exception as e:
            print(f"Warnung: transfers.txt nicht lesbar: {e}")
            _OPTIONAL_TRANSFERS_DF = None
    else:
        _OPTIONAL_TRANSFERS_DF = None

    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    stop_times["stop_sequence"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
    stop_times["arrival_min"] = stop_times["arrival_time"].apply(parse_gtfs_time_to_minutes)
    stop_times["departure_min"] = stop_times["departure_time"].apply(parse_gtfs_time_to_minutes)

    stops = stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].dropna()
    stop_times = stop_times[
        ["trip_id", "arrival_time", "departure_time", "arrival_min", "departure_min",
         "stop_id", "stop_sequence"]
    ].dropna(subset=["trip_id", "stop_id", "stop_sequence", "arrival_min", "departure_min"])

    route_columns = ["route_id", "route_short_name", "route_type"]
    if "agency_id" in routes.columns:
        route_columns.append("agency_id")
    if "route_long_name" in routes.columns:
        route_columns.append("route_long_name")

    routes = routes[route_columns].copy()
    routes.setdefault("agency_id", "")
    routes.setdefault("route_long_name", "")
    routes["agency_id"] = routes.get("agency_id", pd.Series(dtype=str)).fillna("")
    routes["route_long_name"] = routes.get("route_long_name", pd.Series(dtype=str)).fillna("")
    routes["route_short_name"] = routes["route_short_name"].fillna("n/a")
    routes = routes.dropna(subset=["route_id"])

    trips = trips[["trip_id", "route_id"]].dropna(subset=["trip_id", "route_id"])

    print("GTFS-Daten erfolgreich geladen.")
    return stops, stop_times, trips, routes


# ─── Kanten-Vorbereitung ──────────────────────────────────────────────────────

def prepare_transit_edges(stop_times: pd.DataFrame, trips: pd.DataFrame,
                          stops: pd.DataFrame, routes: pd.DataFrame) -> pd.DataFrame:
    """Erstellt gefilterte Transit-Kanten aus GTFS-Daten."""
    merged = (stop_times
              .merge(trips, on="trip_id", how="inner")
              .merge(routes, on="route_id", how="inner"))
    merged = merged.sort_values(["trip_id", "stop_sequence"]).copy()

    merged["next_stop_id"] = merged.groupby("trip_id")["stop_id"].shift(-1)
    merged["next_arrival_min"] = merged.groupby("trip_id")["arrival_min"].shift(-1)

    edges = merged.dropna(subset=["next_stop_id", "next_arrival_min"]).copy()
    edges["time_min"] = edges["next_arrival_min"] - edges["departure_min"]
    edges = edges[(edges["time_min"] > 0) & (edges["time_min"] <= 240)].copy()

    edges = edges.merge(
        stops[["stop_id", "stop_lat", "stop_lon", "stop_name"]], on="stop_id", how="inner"
    )
    edges = edges.merge(
        stops[["stop_id", "stop_lat", "stop_lon", "stop_name"]],
        left_on="next_stop_id", right_on="stop_id", how="inner",
        suffixes=("_start", "_end"),
    )

    edges["distance_km"] = edges.apply(
        lambda x: calc_distance_km(
            x["stop_lat_start"], x["stop_lon_start"],
            x["stop_lat_end"], x["stop_lon_end"]
        ), axis=1
    )

    edges = edges[edges["stop_id_start"] != edges["stop_id_end"]].copy()

    edges["route_type"] = edges["route_type"].astype(str)
    edges["route_short_name"] = edges["route_short_name"].fillna("n/a")
    edges["route_long_name"] = edges["route_long_name"].fillna("")
    edges["agency_id"] = edges["agency_id"].fillna("")

    edges["mode_class"] = edges.apply(
        lambda r: classify_mode(
            r["route_type"], r["route_short_name"],
            r["route_long_name"], r["agency_id"]
        ), axis=1
    )

    # SEV, Ersatzverkehr, unplausible Kanten entfernen
    edges = edges[~edges.apply(should_exclude_transit_edge, axis=1)].copy()

    # Deduplizieren: schnellste Kante pro Stop-Paar + Route
    edges = (edges
             .sort_values(["stop_id_start", "stop_id_end", "route_id", "trip_id", "time_min"])
             .drop_duplicates(subset=["stop_id_start", "stop_id_end", "route_id"], keep="first"))

    return edges


def prepare_transfer_edges(stops: pd.DataFrame) -> pd.DataFrame:
    """Lädt Transfer-Kanten aus transfers.txt (falls vorhanden)."""
    if _OPTIONAL_TRANSFERS_DF is None or _OPTIONAL_TRANSFERS_DF.empty:
        return pd.DataFrame()

    transfers = _OPTIONAL_TRANSFERS_DF.copy()
    required = {"from_stop_id", "to_stop_id"}
    if not required.issubset(set(transfers.columns)):
        return pd.DataFrame()

    if "min_transfer_time" not in transfers.columns:
        transfers["min_transfer_time"] = None

    return transfers.dropna(subset=["from_stop_id", "to_stop_id"]).copy()
