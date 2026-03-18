import json
import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IN_PATH = os.path.join(BASE_DIR, "parking_sites_items_deduped.json")
OUT_JSON = os.path.join(BASE_DIR, "parking_subset_demo.json")
OUT_CSV = os.path.join(BASE_DIR, "parking_subset_demo.csv")

LAT_MIN, LAT_MAX = 48.60, 48.90
LON_MIN, LON_MAX = 9.00, 9.35


def project(it):
    return {
        "source_id": it.get("source_id"),
        "original_uid": it.get("original_uid"),
        "name": it.get("name"),
        "type": it.get("type"),
        "purpose": it.get("purpose"),
        "lat": it.get("lat"),
        "lon": it.get("lon"),
        "capacity": it.get("capacity"),
        "opening_hours": it.get("opening_hours"),
        "has_realtime_data": it.get("has_realtime_data"),
        "static_data_updated_at": it.get("static_data_updated_at"),
    }


if __name__ == "__main__":
    with open(IN_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    subset = []
    for it in items:
        lat, lon = it.get("lat"), it.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
                subset.append(project(it))

    if len(subset) < 50:
        subset = [project(it) for it in items[:500]]

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(subset, f, ensure_ascii=False, indent=2)

    df = pd.DataFrame(subset)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"OK: subset={len(subset)} -> {OUT_JSON}")
