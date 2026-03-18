from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ------------------------------------------------------------
# Multi-Attribute Utility / MCDM basierter Best-Match-Engine
# ------------------------------------------------------------
# Ziel:
# - keine Trainingsdaten notwendig
# - nachvollziehbarer "KI-naher" Entscheidungsprozess
# - nutzerbezogene Gewichtung über gespeicherte Präferenzen
# - kompatibel mit den mode-Dictionaries aus deiner Flask-App
#
# Erwartete mode-Felder (aus comparison_modes):
#   name, total_time_min, co2_g, distance_km, transfers,
#   is_pt, estimated_note, steps, ...
#
# Erwartete preference-Felder:
#   mode_walk, mode_bike, mode_car, mode_pt,
#   max_walk_km, max_bike_km,
#   pref_time_vs_env, pref_comfort,
#   comfort_bike_temp, comfort_walk_temp,
#   prefer_covered_modes, reduce_car_in_snow
# ------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default



def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))



def _norm_benefit(value: float, v_min: float, v_max: float) -> float:
    if math.isclose(v_max, v_min):
        return 1.0
    return _clamp((value - v_min) / (v_max - v_min), 0.0, 1.0)



def _norm_cost(value: float, v_min: float, v_max: float) -> float:
    if math.isclose(v_max, v_min):
        return 1.0
    return _clamp((v_max - value) / (v_max - v_min), 0.0, 1.0)



def _avg_temp(weather_origin: Optional[dict], weather_destination: Optional[dict]) -> Optional[float]:
    temps: List[float] = []
    for weather in (weather_origin, weather_destination):
        if weather and weather.get("temp_c") is not None:
            temps.append(_safe_float(weather.get("temp_c")))
    if not temps:
        return None
    return sum(temps) / len(temps)



def _max_precipitation(weather_origin: Optional[dict], weather_destination: Optional[dict]) -> float:
    values = []
    for weather in (weather_origin, weather_destination):
        if weather and weather.get("precipitation_mm") is not None:
            values.append(_safe_float(weather.get("precipitation_mm")))
    return max(values) if values else 0.0



def _max_cloud_cover(weather_origin: Optional[dict], weather_destination: Optional[dict]) -> float:
    values = []
    for weather in (weather_origin, weather_destination):
        if weather and weather.get("cloud_cover_pct") is not None:
            values.append(_safe_float(weather.get("cloud_cover_pct")))
    return max(values) if values else 0.0



def _weather_condition_set(weather_origin: Optional[dict], weather_destination: Optional[dict]) -> set:
    values = set()
    for weather in (weather_origin, weather_destination):
        if weather and weather.get("condition"):
            values.add(str(weather.get("condition")).strip().lower())
    return values



def _is_mode_enabled(mode_name: str, preferences: dict) -> bool:
    name = (mode_name or "").strip().lower()
    if "zu fuß" in name or "fuss" in name:
        return bool(preferences.get("mode_walk", True))
    if "fahrrad" in name or "bike" in name:
        return bool(preferences.get("mode_bike", True))
    if "auto" in name:
        return bool(preferences.get("mode_car", True))
    if "öpnv" in name or "bahn" in name or "pt" in name:
        return bool(preferences.get("mode_pt", True))
    return True



def _is_covered_mode(mode_name: str, mode: dict) -> bool:
    name = (mode_name or "").strip().lower()
    if mode.get("is_pt"):
        return True
    return "auto" in name



def _extract_transfers(mode: dict) -> int:
    return _safe_int(mode.get("transfers"), 0) if mode.get("show_transfers") else 0



def _distance_penalty(mode_name: str, mode: dict, preferences: dict) -> Tuple[float, Optional[str]]:
    distance_km = _safe_float(mode.get("distance_km"), 0.0)
    name = (mode_name or "").strip().lower()

    if "zu fuß" in name or "fuss" in name:
        max_walk = _safe_float(preferences.get("max_walk_km"), 2.0)
        if distance_km <= max_walk:
            return 0.0, None
        over = distance_km - max_walk
        penalty = _clamp(over / max(max_walk, 0.5), 0.0, 1.0)
        return penalty, f"Fußdistanz über Komfortgrenze ({distance_km:.1f} km > {max_walk:.1f} km)"

    if "fahrrad" in name or "bike" in name:
        max_bike = _safe_float(preferences.get("max_bike_km"), 10.0)
        if distance_km <= max_bike:
            return 0.0, None
        over = distance_km - max_bike
        penalty = _clamp(over / max(max_bike, 1.0), 0.0, 1.0)
        return penalty, f"Fahrraddistanz über Komfortgrenze ({distance_km:.1f} km > {max_bike:.1f} km)"

    return 0.0, None



def _temperature_penalty(mode_name: str, preferences: dict, avg_temp_c: Optional[float]) -> Tuple[float, Optional[str]]:
    if avg_temp_c is None:
        return 0.0, None

    name = (mode_name or "").strip().lower()

    if "fahrrad" in name or "bike" in name:
        comfort_temp = _safe_float(preferences.get("comfort_bike_temp"), 15.0)
        diff = max(0.0, comfort_temp - avg_temp_c)
        penalty = _clamp(diff / 20.0, 0.0, 1.0)
        if penalty > 0.2:
            return penalty, f"Temperatur für Fahrrad eher unkomfortabel ({avg_temp_c:.1f} °C < {comfort_temp:.1f} °C)"
        return penalty, None

    if "zu fuß" in name or "fuss" in name:
        comfort_temp = _safe_float(preferences.get("comfort_walk_temp"), 10.0)
        diff = max(0.0, comfort_temp - avg_temp_c)
        penalty = _clamp(diff / 20.0, 0.0, 1.0)
        if penalty > 0.2:
            return penalty, f"Temperatur für Fußweg eher unkomfortabel ({avg_temp_c:.1f} °C < {comfort_temp:.1f} °C)"
        return penalty, None

    return 0.0, None



def _weather_penalty(mode_name: str, mode: dict, preferences: dict, weather_origin: Optional[dict], weather_destination: Optional[dict]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    penalty = 0.0

    precip = _max_precipitation(weather_origin, weather_destination)
    conditions = _weather_condition_set(weather_origin, weather_destination)
    covered = _is_covered_mode(mode_name, mode)

    if bool(preferences.get("prefer_covered_modes", False)) and precip > 0.2 and not covered:
        rain_penalty = _clamp(precip / 4.0, 0.0, 1.0)
        penalty += rain_penalty
        reasons.append("bei Regen nicht überdacht")

    snow_like = {"snow", "snow showers", "freezing rain", "sleet"}
    if bool(preferences.get("reduce_car_in_snow", False)) and "auto" in (mode_name or "").lower() and conditions.intersection(snow_like):
        snow_penalty = 0.9
        penalty += snow_penalty
        reasons.append("Auto bei Schnee unattraktiver gewichtet")

    return _clamp(penalty, 0.0, 1.0), reasons



def _mode_preference_score(mode_name: str, preferences: dict) -> float:
    return 1.0 if _is_mode_enabled(mode_name, preferences) else 0.0



def _build_weights(preferences: dict) -> Dict[str, float]:
    # Nutzerwerte 0..100 in Gewichte übersetzen
    time_pref = _safe_float(preferences.get("pref_time_vs_env"), 50.0) / 100.0
    comfort_pref = _safe_float(preferences.get("pref_comfort"), 60.0) / 100.0

    # Mehr Gewicht auf Zeit, wenn time_pref hoch ist
    # Mehr Gewicht auf Umwelt, wenn time_pref niedrig ist
    weights = {
        "time": 0.18 + 0.30 * time_pref,
        "co2": 0.18 + 0.30 * (1.0 - time_pref),
        "comfort": 0.10 + 0.22 * comfort_pref,
        "weather": 0.08 + 0.12 * comfort_pref,
        "preference": 0.10,
        "distance_fit": 0.12,
    }

    # Normieren auf exakt 1.0
    total = sum(weights.values())
    if total <= 0:
        return {key: 1.0 / len(weights) for key in weights}
    return {key: value / total for key, value in weights.items()}



def _mode_reason_prefix(mode_name: str) -> str:
    name = (mode_name or "").strip()
    if not name:
        return "Diese Option"
    return name



def score_modes(
    comparison_modes: List[dict],
    preferences: dict,
    weather_origin: Optional[dict] = None,
    weather_destination: Optional[dict] = None,
) -> List[dict]:
    """
    Bewertet alle Alternativen und liefert eine Liste mit Detail-Scores zurück.
    Höherer utility_score = besser.
    """
    if not comparison_modes:
        return []

    modes = [dict(mode) for mode in comparison_modes]
    weights = _build_weights(preferences)
    avg_temp_c = _avg_temp(weather_origin, weather_destination)

    times = [_safe_float(m.get("total_time_min"), math.inf) for m in modes]
    co2s = [_safe_float(m.get("co2_g"), math.inf) for m in modes]
    transfers = [_extract_transfers(m) for m in modes]

    finite_times = [v for v in times if math.isfinite(v)] or [0.0]
    finite_co2s = [v for v in co2s if math.isfinite(v)] or [0.0]

    min_time, max_time = min(finite_times), max(finite_times)
    min_co2, max_co2 = min(finite_co2s), max(finite_co2s)
    min_transfers, max_transfers = min(transfers), max(transfers)

    scored_modes: List[dict] = []

    for mode in modes:
        mode_name = str(mode.get("name", "Unbekannt"))
        reasons_positive: List[str] = []
        reasons_negative: List[str] = []

        enabled = _is_mode_enabled(mode_name, preferences)
        preference_score = _mode_preference_score(mode_name, preferences)
        if enabled:
            reasons_positive.append("Modus ist in den Präferenzen aktiviert")
        else:
            reasons_negative.append("Modus wurde in den Präferenzen deaktiviert")

        time_value = _safe_float(mode.get("total_time_min"), math.inf)
        co2_value = _safe_float(mode.get("co2_g"), math.inf)
        transfers_value = _extract_transfers(mode)

        time_score = _norm_cost(time_value, min_time, max_time)
        co2_score = _norm_cost(co2_value, min_co2, max_co2)
        transfer_score = _norm_cost(float(transfers_value), float(min_transfers), float(max_transfers))

        if time_score >= 0.8:
            reasons_positive.append("sehr gute Reisezeit im Vergleich zu den Alternativen")
        elif time_score <= 0.25:
            reasons_negative.append("vergleichsweise lange Reisezeit")

        if co2_score >= 0.8:
            reasons_positive.append("sehr gute CO₂-Bilanz")
        elif co2_score <= 0.25:
            reasons_negative.append("vergleichsweise hohe CO₂-Belastung")

        comfort_raw = transfer_score
        if transfers_value <= 1 and mode.get("show_transfers"):
            reasons_positive.append("wenige Umstiege")
        elif transfers_value >= 3:
            reasons_negative.append("mehrere Umstiege")
        elif not mode.get("show_transfers"):
            reasons_positive.append("direkte Strecke ohne Umstiege")

        distance_penalty, distance_reason = _distance_penalty(mode_name, mode, preferences)
        distance_fit_score = 1.0 - distance_penalty
        if distance_reason:
            reasons_negative.append(distance_reason)
        elif ("zu fuß" in mode_name.lower() or "fuss" in mode_name.lower() or "fahrrad" in mode_name.lower() or "bike" in mode_name.lower()):
            reasons_positive.append("Distanz liegt innerhalb der Komfortgrenze")

        temp_penalty, temp_reason = _temperature_penalty(mode_name, preferences, avg_temp_c)
        if temp_reason:
            reasons_negative.append(temp_reason)
        elif avg_temp_c is not None and ("zu fuß" in mode_name.lower() or "fuss" in mode_name.lower() or "fahrrad" in mode_name.lower() or "bike" in mode_name.lower()):
            reasons_positive.append("Temperatur passt gut zur Komfortpräferenz")

        weather_penalty, weather_reasons = _weather_penalty(
            mode_name,
            mode,
            preferences,
            weather_origin,
            weather_destination,
        )
        reasons_negative.extend(weather_reasons)
        if weather_penalty == 0 and (_max_precipitation(weather_origin, weather_destination) > 0.2):
            if _is_covered_mode(mode_name, mode):
                reasons_positive.append("bei Niederschlag vorteilhaft, da überdacht")

        comfort_score = _clamp(comfort_raw - 0.55 * temp_penalty - 0.35 * weather_penalty, 0.0, 1.0)
        weather_score = _clamp(1.0 - max(temp_penalty, weather_penalty), 0.0, 1.0)

        utility_score = (
            weights["time"] * time_score
            + weights["co2"] * co2_score
            + weights["comfort"] * comfort_score
            + weights["weather"] * weather_score
            + weights["preference"] * preference_score
            + weights["distance_fit"] * distance_fit_score
        )

        if not enabled:
            utility_score *= 0.05

        score_0_100 = round(utility_score * 100.0, 1)

        explanation: List[str] = []
        for reason in reasons_positive[:3]:
            explanation.append(f"Pluspunkt: {reason}")
        for reason in reasons_negative[:3]:
            explanation.append(f"Abzug: {reason}")

        scored = dict(mode)
        scored.update(
            {
                "utility_score": round(utility_score, 4),
                "score_0_100": score_0_100,
                "maut_breakdown": {
                    "weights": {k: round(v, 4) for k, v in weights.items()},
                    "time_score": round(time_score, 4),
                    "co2_score": round(co2_score, 4),
                    "comfort_score": round(comfort_score, 4),
                    "weather_score": round(weather_score, 4),
                    "preference_score": round(preference_score, 4),
                    "distance_fit_score": round(distance_fit_score, 4),
                    "temperature_penalty": round(temp_penalty, 4),
                    "weather_penalty": round(weather_penalty, 4),
                    "transfers": transfers_value,
                },
                "maut_explanation": explanation,
                "maut_enabled": enabled,
            }
        )
        scored_modes.append(scored)

    scored_modes.sort(
        key=lambda mode: (
            -_safe_float(mode.get("utility_score"), -1.0),
            _safe_float(mode.get("total_time_min"), math.inf),
            _safe_float(mode.get("co2_g"), math.inf),
        )
    )

    return scored_modes



def build_best_match_result(
    comparison_modes: List[dict],
    preferences: dict,
    weather_origin: Optional[dict] = None,
    weather_destination: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Hauptfunktion für die App.

    Rückgabe:
    {
        "best_mode": {...},
        "ranked_modes": [...],
        "decision_summary": [...],
    }
    """
    ranked_modes = score_modes(
        comparison_modes=comparison_modes,
        preferences=preferences,
        weather_origin=weather_origin,
        weather_destination=weather_destination,
    )

    if not ranked_modes:
        return {
            "best_mode": None,
            "ranked_modes": [],
            "decision_summary": ["Keine Alternativen zur Bewertung vorhanden."],
        }

    best_mode = dict(ranked_modes[0])
    summary: List[str] = []
    prefix = _mode_reason_prefix(best_mode.get("name"))
    summary.append(f"{prefix} erzielt den höchsten Gesamtnutzen nach dem Multi-Attribute-Utility-Modell.")

    for item in best_mode.get("maut_explanation", [])[:4]:
        summary.append(item)

    return {
        "best_mode": best_mode,
        "ranked_modes": ranked_modes,
        "decision_summary": summary,
    }



def patch_best_mode_card(best_mode: Optional[dict]) -> Optional[dict]:
    """
    Passt das Gewinner-Dictionary so an, dass es direkt in deiner UI als Best-Match-Karte
    verwendet werden kann.
    """
    if not best_mode:
        return None

    patched = dict(best_mode)
    patched["badge_best_match"] = True
    patched["name"] = f"{best_mode.get('name', 'Unbekannt')} – Best Match"

    explanation_lines = best_mode.get("maut_explanation", [])[:3]
    if explanation_lines:
        patched["description"] = " | ".join(explanation_lines)

    return patched


# ------------------------------------------------------------
# Beispiel für Integration in app.py
# ------------------------------------------------------------
# from best_match_engine import build_best_match_result, patch_best_mode_card
#
# preferences_data = _read_preferences()
# result = build_best_match_result(
#     comparison_modes=comparison_modes,
#     preferences=preferences_data,
#     weather_origin=weather_origin,
#     weather_destination=weather_destination,
# )
# best_match_route = patch_best_mode_card(result["best_mode"])
# comparison_modes = result["ranked_modes"]
# ------------------------------------------------------------
