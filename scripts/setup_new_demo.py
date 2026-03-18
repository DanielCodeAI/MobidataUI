from pathlib import Path
import pandas as pd


def build_routes_df():
    columns = [
        "route_id", "name", "mode_combo", "total_distance_km", "total_time_min",
        "walk_km", "bike_km", "car_km", "pt_km", "transfers",
        "has_parking", "has_charging", "description",
    ]
    data = [
        ["R1", "Fahrrad (direkt)", "bike", 190.0, 600, 0.0, 190.0, 0.0, 0.0, 0, False, False,
         "Direkte Fahrradroute Stuttgart-Freiburg ohne Umstiege."],
        ["R2", "OEPNV (S-Bahn + Fussweg)", "walk+pt", 195.0, 150, 3.0, 0.0, 0.0, 192.0, 1, False, False,
         "Fussweg zur Haltestelle, Fernzug nach Freiburg, kurzer Fussweg zum Ziel."],
        ["R3", "Auto (direkt)", "car", 200.0, 130, 0.0, 0.0, 200.0, 0.0, 0, False, False,
         "Direkte Autoroute Stuttgart-Freiburg ueber Autobahn."],
        ["R4", "Auto -> P+R -> OEPNV", "car+walk+pt", 195.0, 140, 1.0, 0.0, 30.0, 164.0, 1, True, True,
         "Mit dem Auto zum P+R, dort parken/laden, weiter mit Zug nach Freiburg."],
        ["R5", "Zu Fuss (direkt)", "walk", 190.0, 2400, 190.0, 0.0, 0.0, 0.0, 0, False, False,
         "Theoretische Fussroute Stuttgart-Freiburg (Extremfall)."],
    ]
    return pd.DataFrame(data, columns=columns)


def build_segments_df():
    columns = ["route_id", "segment_index", "mode", "distance_km", "time_min", "description"]
    data = [
        ["R1", 1, "bike", 190.0, 600, "Fahrradroute direkt Stuttgart-Freiburg"],
        ["R2", 1, "walk", 1.0, 15, "Start -> Bahnhof Stuttgart (Fussweg)"],
        ["R2", 2, "pt", 192.0, 115, "Fernzug/Regionalzug Stuttgart -> Freiburg"],
        ["R2", 3, "walk", 2.0, 20, "Bahnhof Freiburg -> Ziel (Fussweg)"],
        ["R3", 1, "car", 200.0, 130, "Direkte Autofahrt Stuttgart -> Freiburg"],
        ["R4", 1, "car", 30.0, 25, "Start -> P+R-Parkplatz bei Stuttgart"],
        ["R4", 2, "walk", 0.5, 7, "P+R -> Bahnhof (Fussweg)"],
        ["R4", 3, "pt", 164.0, 103, "Zug P+R-Bahnhof -> Freiburg"],
        ["R4", 4, "walk", 0.5, 5, "Bahnhof Freiburg -> Ziel (Fussweg)"],
        ["R5", 1, "walk", 190.0, 2400, "Gesamter Weg Stuttgart -> Freiburg zu Fuss"],
    ]
    return pd.DataFrame(data, columns=columns)


def build_scored_df(routes_df):
    co2_car, co2_pt = 164.0, 42.0
    en_car, en_pt, en_bike, en_walk = 600.0, 100.0, 25.0, 15.0
    df = routes_df.copy()
    df["co2_g"] = df["car_km"] * co2_car + df["pt_km"] * co2_pt
    df["energy_Wh"] = df["car_km"] * en_car + df["pt_km"] * en_pt + df["bike_km"] * en_bike + df["walk_km"] * en_walk

    def norm(col):
        mn, mx = col.min(), col.max()
        return (col * 0) if mx == mn else (col - mn) / (mx - mn)

    w_time, w_co2, w_energy = 0.6, 0.3, 0.1
    df["score_raw"] = w_time * norm(df["total_time_min"]) + w_co2 * norm(df["co2_g"]) + w_energy * norm(df["energy_Wh"])
    df["score_0_100"] = (100 - df["score_raw"] * 100).round(1)
    df["badge_fastest"] = df["total_time_min"] == df["total_time_min"].min()
    df["badge_eco_best"] = df["route_id"] == "R1"
    df["badge_best_match"] = df["score_0_100"] == df["score_0_100"].max()
    df = df.sort_values("score_0_100", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df


def main():
    root = Path(__file__).resolve().parents[1]
    demo_dir = root / "data" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    routes = build_routes_df()
    segments = build_segments_df()
    scored = build_scored_df(routes)

    routes.to_csv(demo_dir / "routes_demo.csv", index=False, encoding="utf-8")
    segments.to_csv(demo_dir / "route_segments_demo.csv", index=False, encoding="utf-8")
    scored.to_csv(demo_dir / "routes_scored_demo.csv", index=False, encoding="utf-8")

    print(f"Demo-Daten geschrieben nach: {demo_dir}")


if __name__ == "__main__":
    main()
