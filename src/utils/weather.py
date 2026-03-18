import requests
from datetime import datetime

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def geocode_city(name: str, country: str = "DE"):
    """
    Wandelt einen Ortsnamen in Koordinaten um.
    Liefert None, wenn nichts gefunden wird.
    """
    if not name:
        return None

    params = {
        "name": name,
        "count": 1,
        "language": "de",
        "format": "json",
    }
    if country:
        params["country"] = country

    r = requests.get(GEOCODE_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    results = data.get("results") or []
    if not results:
        return None

    first = results[0]
    return {
        "name": first.get("name"),
        "lat": first.get("latitude"),
        "lon": first.get("longitude"),
    }

def fetch_hourly_weather(lat: float, lon: float, when: datetime):
    """
    Holt stündliche Werte für den Tag von 'when' und pickt den Slot,
    der zeitlich am nächsten an 'when' liegt.
    """
    date_str = when.date().isoformat()

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "precipitation",
            "rain",
            "snowfall",
            "cloudcover",
            "windspeed_10m",
            "weathercode",
        ]),
        "timezone": "auto",
        "start_date": date_str,
        "end_date": date_str,
    }

    r = requests.get(FORECAST_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    hourly = data.get("hourly", {})

    times = hourly.get("time", [])
    if not times:
        return None

    # Zeitpunkt auf ganze Stunde runden
    target = when.replace(minute=0, second=0, microsecond=0)
    target_str = target.isoformat(timespec="hours")

    # Index der passenden Stunde suchen (exakte Stunde oder erster Fallback)
    idx = None
    for i, t in enumerate(times):
        if t.startswith(target_str):
            idx = i
            break
    if idx is None:
        idx = 0  # Fallback: erste Stunde des Tages

    return {
        "time": times[idx],
        "temperature_c": hourly["temperature_2m"][idx],
        "apparent_temperature_c": hourly["apparent_temperature"][idx],
        "precipitation_mm": hourly["precipitation"][idx],
        "rain_mm": hourly["rain"][idx],
        "snowfall_mm": hourly["snowfall"][idx],
        "cloud_cover_pct": hourly["cloudcover"][idx],
        "wind_speed_10m_kmh": hourly["windspeed_10m"][idx],
        "weather_code": hourly["weathercode"][idx],
    }
def _icon_for_code(code: int) -> str:
    # Stark vereinfachte Mapping-Tabelle
    if code in (0, 1):
        return "☀️"
    if code in (2,):
        return "⛅"
    if code in (3, 45, 48):
        return "☁️"
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return "🌧️"
    if code in (71, 73, 75, 85, 86):
        return "❄️"
    if code in (95, 96, 99):
        return "⛈️"
    return "❓"


def _condition_for_code(code: int) -> str:
    if code in (0, 1):
        return "klar"
    if code in (2,):
        return "leicht bewölkt"
    if code in (3, 45, 48):
        return "stark bewölkt"
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
        return "Regen"
    if code in (71, 73, 75, 85, 86):
        return "Schnee"
    if code in (95, 96, 99):
        return "Gewitter"
    return "unbekannt"


from typing import Dict, Any, Optional


def compute_weather_flags(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Interpretiert die Rohdaten von Open-Meteo und gibt ein UI-freundliches Dict
    zurück. Achtet darauf, dass 'Regen' nicht mit 0.0 mm Niederschlag kombiniert wird.
    """
    if raw is None:
        return None

    temp = float(raw.get("temperature_c", 0.0))
    apparent = float(raw.get("apparent_temperature_c", temp))
    cloud = float(raw.get("cloud_cover_pct", 0.0))
    wind = float(raw.get("wind_speed_10m_kmh", 0.0))
    code = int(raw.get("weather_code", -1))

    # Einzelwerte aus dem API
    precip = float(raw.get("precipitation_mm", 0.0))
    rain = float(raw.get("rain_mm", 0.0))
    snow = float(raw.get("snowfall_mm", 0.0))

    # "Logischer" Niederschlag: maximaler der drei Werte
    precip_total = max(precip, rain, snow)

    # Für die Anzeige runden wir auf 1 Nachkommastelle
    precip_display = round(precip_total, 1)

    # Einfaches Mapping für den Wetterzustand
    # (ggf. an deine Codes anpassen)
    if precip_total >= 0.1 and snow >= rain:
        condition = "Schnee"
        icon = "🌨️"
    elif precip_total >= 0.1 and rain >= snow:
        condition = "Regen"
        icon = "🌧️"
    else:
        # Kein nennenswerter Niederschlag -> trocken
        if cloud < 20:
            condition = "Sonnig"
            icon = "☀️"
        elif cloud < 60:
            condition = "Wolkig"
            icon = "⛅"
        else:
            condition = "Stark bewölkt"
            icon = "☁️"

    return {
        "time": raw.get("time"),
        "temp_c": round(temp, 1),
        "apparent_temperature_c": round(apparent, 1),
        "cloud_cover_pct": int(round(cloud)),
        "wind_speed_10m_kmh": round(wind, 1),
        "weather_code": code,
        "precipitation_mm": precip_display,
        "rain_mm": round(rain, 1),
        "snowfall_mm": round(snow, 1),
        "condition": condition,
        "icon": icon,
    }

def fetch_weather_for_place(place_name: str, when: datetime, country: str = "DE"):
    loc = geocode_city(place_name, country=country)
    if not loc:
        return {
            "location_name": place_name or "Unbekannt",
            "error": "Ort nicht gefunden",
            "icon": "❓",
            "condition": "unbekannt",
            "temp_c": 0.0,
            "apparent_temperature_c": 0.0,
            "precipitation_mm": 0.0,
            "cloud_cover_pct": 0,
            "wind_speed_10m_kmh": 0.0,
        }

    raw = fetch_hourly_weather(loc["lat"], loc["lon"], when)
    flags = compute_weather_flags(raw)
    flags["location_name"] = loc["name"]
    return flags
