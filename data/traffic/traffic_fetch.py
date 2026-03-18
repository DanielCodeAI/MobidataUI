import os
import json
import csv
import requests
import xml.etree.ElementTree as ET
from collections import Counter

URL = "https://api.mobidata-bw.de/datasets/traffic/incidents-bw/TIC3-Meldungen.xml"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_XML = os.path.join(BASE_DIR, "traffic_incidents.xml")
OUT_JSON = os.path.join(BASE_DIR, "traffic_incidents_flat.json")
OUT_CSV = os.path.join(BASE_DIR, "traffic_incidents_flat.csv")


def strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag

def text_of(el):
    return (el.text or "").strip() if el is not None else ""

def find_first(el, *names):
    if el is None:
        return None
    for node in el.iter():
        if strip_ns(node.tag) in names:
            return node
    return None

def collect_all_text(el, tag_name):
    return [text_of(n) for n in el.iter() if strip_ns(n.tag) == tag_name and text_of(n)]


def main():
    r = requests.get(URL, timeout=60)
    r.raise_for_status()
    xml_bytes = r.content

    with open(OUT_XML, "wb") as f:
        f.write(xml_bytes)
    print(f"OK: XML gespeichert -> {OUT_XML} ({len(xml_bytes)} bytes)")

    root = ET.fromstring(xml_bytes)
    candidates = list(root) or [root]
    incidents = []

    for i, entry in enumerate(candidates):
        tic_id = text_of(find_first(entry, "ticId", "id", "Identifier")) or f"entry_{i}"
        texts = collect_all_text(entry, "Text")
        areas = collect_all_text(entry, "Name")
        unique_areas = list(dict.fromkeys(areas))

        incidents.append({
            "tic_id": tic_id,
            "category": text_of(find_first(entry, "Category")),
            "subcategory": text_of(find_first(entry, "SubCategory")),
            "road_name": text_of(find_first(entry, "RoadName")),
            "distance": text_of(find_first(entry, "Distance")),
            "text": " | ".join(texts[:3]),
            "areas": unique_areas[:6],
        })

    incidents = [x for x in incidents if x.get("text") or x.get("road_name") or x.get("category")]

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tic_id", "category", "subcategory", "road_name", "distance", "text", "areas"])
        w.writeheader()
        for row in incidents:
            row = dict(row)
            row["areas"] = "; ".join(row.get("areas") or [])
            w.writerow(row)

    cats = Counter([x.get("category") for x in incidents if x.get("category")])
    print(f"OK: {len(incidents)} Meldungen. Top: {cats.most_common(5)}")


if __name__ == "__main__":
    main()
