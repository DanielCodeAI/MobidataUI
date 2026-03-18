import os
import json
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEATHER_DIR = os.path.join(BASE_DIR, "data", "weather")
os.makedirs(WEATHER_DIR, exist_ok=True)

API_URL = "https://api.open-meteo.com/v1/forecast"


def get_current_weather(lat, lon, timezone="Europe/Berlin"):
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "precipitation",
            "rain", "snowfall", "is_day", "cloud_cover",
            "wind_speed_10m", "weather_code",
        ]),
        "timezone": timezone,
    }
    resp = requests.get(API_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    current = data.get("current", {})
    rain_mm = float(current.get("rain", 0) or 0)
    snow_mm = float(current.get("snowfall", 0) or 0)
    precip_mm = float(current.get("precipitation", 0) or 0)
    return {
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "time": current.get("time"),
        "temperature_c": current.get("temperature_2m"),
        "apparent_temperature_c": current.get("apparent_temperature"),
        "precipitation_mm": precip_mm,
        "rain_mm": rain_mm,
        "snowfall_mm": snow_mm,
        "is_rain": rain_mm > 0.0,
        "is_snow": snow_mm > 0.0,
        "cloud_cover_pct": current.get("cloud_cover"),
        "wind_speed_10m_kmh": current.get("wind_speed_10m"),
        "is_day": bool(current.get("is_day", 1)),
        "weather_code": current.get("weather_code"),
    }


if __name__ == "__main__":
    weather = get_current_weather(48.78, 9.18)
    out_path = os.path.join(WEATHER_DIR, "current_stuttgart.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(weather, f, ensure_ascii=False, indent=2)
    print(f"Wetterdaten gespeichert unter: {out_path}")
    print(json.dumps(weather, ensure_ascii=False, indent=2))
