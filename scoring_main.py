import os
import pandas as pd

# === Plattformunabhaengige Pfade (relativ zum Projektverzeichnis) ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEMO_DIR    = os.path.join(BASE_DIR, "data", "demo")
SCORING_DIR = os.path.join(BASE_DIR, "scoring_CSV")

ROUTES_PATH   = os.path.join(DEMO_DIR, "routes_demo.csv")
SEGMENTS_PATH = os.path.join(DEMO_DIR, "route_segments_demo.csv")
EMISS_PATH    = os.path.join(SCORING_DIR, "emission_factors.csv")
ENERGY_PATH   = os.path.join(SCORING_DIR, "energy_factors.csv")

OUT_PATH      = os.path.join(DEMO_DIR, "routes_scored_demo.csv")


# --- Hilfsfunktionen ---

def load_factors():
    em = pd.read_csv(EMISS_PATH)
    en = pd.read_csv(ENERGY_PATH)

    em = em.set_index("mode")["co2_g_per_pkm"].to_dict()
    en = en.set_index("mode")["energy_Wh_per_pkm"].to_dict()
    return em, en


def factor_for_mode(mode: str, em_factors: dict, en_factors: dict):
    """
    Mappt unsere Demo-Modes ('car','pt','bike','walk') auf die
    passenden rows in den Faktoren-Tabellen.
    """
    if mode == "car":
        key = "car_avg"
    elif mode == "pt":
        key = "tram_ubahn"
    elif mode == "bike":
        key = "bike"
    elif mode == "walk":
        key = "walk"
    else:
        key = "car_avg"

    co2 = em_factors.get(key, 0.0)
    en  = en_factors.get(key, 0.0)
    return co2, en


def min_max_series(x: pd.Series):
    """Min-Max-Normalisierung auf [0,1]. Bei Konstante -> 0."""
    x_min = x.min()
    x_max = x.max()
    if x_max == x_min:
        return pd.Series(0.0, index=x.index)
    return (x - x_min) / (x_max - x_min)


# --- Hauptlogik ---

def main():
    # 1) Daten laden
    routes   = pd.read_csv(ROUTES_PATH)
    segments = pd.read_csv(SEGMENTS_PATH)
    em_factors, en_factors = load_factors()

    # 2) CO2 & Energie segmentweise berechnen
    co2_list = []
    en_list  = []

    for _, row in segments.iterrows():
        mode = row["mode"]
        dist = row["distance_km"]

        co2_per_pkm, en_per_pkm = factor_for_mode(mode, em_factors, en_factors)

        co2_total = dist * co2_per_pkm        # g CO2
        en_total  = dist * en_per_pkm         # Wh

        co2_list.append(co2_total)
        en_list.append(en_total)

    segments["co2_g"]      = co2_list
    segments["energy_Wh"]  = en_list

    # 3) Aggregation auf Routenebene
    agg = segments.groupby("route_id")[["co2_g", "energy_Wh"]].sum().reset_index()

    routes_scored = routes.merge(agg, on="route_id", how="left")

    # 4) Scoring: Zeit / CO2 / Energie
    time_norm = min_max_series(routes_scored["total_time_min"])
    co2_norm  = min_max_series(routes_scored["co2_g"])
    en_norm   = min_max_series(routes_scored["energy_Wh"])

    # Nutzen = 1 - norm (weniger Zeit/CO2/Energie -> hoeherer Nutzen)
    util_time = 1 - time_norm
    util_co2  = 1 - co2_norm
    util_en   = 1 - en_norm

    # Gewichte
    w_time   = 0.4
    w_co2    = 0.4
    w_energy = 0.2

    score = (
        w_time   * util_time +
        w_co2    * util_co2  +
        w_energy * util_en
    )

    routes_scored["score_raw"] = score
    routes_scored["score_0_100"] = (score * 100).round(1)

    # 5) Rankings / Badges
    eco_best_id = routes_scored.loc[routes_scored["co2_g"].idxmin(), "route_id"]
    fast_best_id = routes_scored.loc[routes_scored["total_time_min"].idxmin(), "route_id"]
    best_score_id = routes_scored.loc[routes_scored["score_raw"].idxmax(), "route_id"]

    routes_scored["badge_eco_best"]   = routes_scored["route_id"].eq(eco_best_id)
    routes_scored["badge_fastest"]    = routes_scored["route_id"].eq(fast_best_id)
    routes_scored["badge_best_match"] = routes_scored["route_id"].eq(best_score_id)

    routes_scored = routes_scored.sort_values("score_raw", ascending=False)
    routes_scored["rank"] = range(1, len(routes_scored) + 1)

    # 6) Speichern
    os.makedirs(DEMO_DIR, exist_ok=True)
    routes_scored.to_csv(OUT_PATH, index=False, encoding="utf-8")

    print(f"Scoring abgeschlossen. Datei gespeichert unter:\n{OUT_PATH}")
    print(routes_scored[[
        "route_id", "name", "total_time_min", "co2_g", "energy_Wh",
        "score_0_100", "rank", "badge_eco_best", "badge_fastest", "badge_best_match"
    ]])


if __name__ == "__main__":
    main()
