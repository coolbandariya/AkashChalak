from __future__ import annotations

import os
from math import atan2, cos, radians, sin, sqrt

from app.services.live_sources import live_bundle
from app.services.sample_data import build_observations

BREAKPOINTS = {
    "pm25": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200), (251, 350, 201, 300), (351, 430, 301, 400), (431, 600, 401, 500)],
    "no2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200), (181, 280, 201, 300), (281, 400, 301, 400), (401, 1000, 401, 500)],
    "so2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200), (381, 800, 201, 300), (801, 1600, 301, 400), (1601, 2000, 401, 500)],
    "co": [(0, 1, 0, 50), (1.1, 2, 51, 100), (2.1, 10, 101, 200), (10.1, 17, 201, 300), (17.1, 34, 301, 400), (34.1, 50, 401, 500)],
    "o3": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 168, 101, 200), (169, 208, 201, 300), (209, 748, 301, 400), (749, 1000, 401, 500)],
}


def _category(aqi: int) -> str:
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Satisfactory"
    if aqi <= 200:
        return "Moderate"
    if aqi <= 300:
        return "Poor"
    if aqi <= 400:
        return "Very Poor"
    return "Severe"


def _fallback_aqi(row: dict) -> int:
    satellite_signal = row["aod"] * 145 + row["no2"] * 1_500_000 + row["so2"] * 850_000
    combustion_signal = row["co"] * 900 + row["fire_count"] * 2.3 + row["hcho"] * 360_000
    met_penalty = max(0, 3.2 - row["wind_speed"]) * 14 + max(0, row["relative_humidity"] - 65) * 0.7
    blended = 0.38 * row["cpcb_station_aqi"] + 0.34 * satellite_signal + 0.2 * combustion_signal + met_penalty
    return max(25, min(450, round(blended)))


def predict_surface_aqi() -> dict:
    bundle = live_bundle()
    cpcb_records = bundle["cpcb_records"]
    if cpcb_records:
        station_features = _predict_from_cpcb(cpcb_records)
        coverage = _augment_with_interpolated_grid(station_features)
        return {
            "features": coverage["features"],
            "sources": bundle["sources"],
            "mode": "live",
            "summary": {
                "station_points": coverage["station_points"],
                "interpolated_points": coverage["interpolated_points"],
                "total_points": len(coverage["features"]),
            },
        }
    if os.getenv("ALLOW_DEMO_FALLBACK", "").lower() == "true":
        demo = _predict_from_demo()
        return {
            "features": demo,
            "sources": bundle["sources"],
            "mode": "demo_fallback",
            "summary": {
                "station_points": len(demo),
                "interpolated_points": 0,
                "total_points": len(demo),
            },
        }
    return {
        "features": [],
        "sources": bundle["sources"],
        "mode": "no_live_data",
        "summary": {"station_points": 0, "interpolated_points": 0, "total_points": 0},
    }


def _predict_from_demo() -> list[dict]:
    features = []
    for row in build_observations():
        aqi = _fallback_aqi(row)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": {
                    **row,
                    "predicted_aqi": aqi,
                    "category": _category(aqi),
                    "confidence": round(0.68 + min(row["wind_speed"], 5) * 0.035, 2),
                    "model": "CNN-LSTM feature contract with deterministic fallback",
                },
            }
        )
    return features


def _predict_from_cpcb(records: list[dict]) -> list[dict]:
    features = []
    for record in records:
        pollutants = record["pollutants"]
        sub_indices = {key: _sub_index(key, value) for key, value in pollutants.items()}
        valid = {key: value for key, value in sub_indices.items() if value is not None}
        if not valid:
            continue
        dominant_pollutant, aqi = max(valid.items(), key=lambda item: item[1])
        props = {
            "city": record["city"],
            "station": record["station"],
            "state": record["state"],
            "lat": record["lat"],
            "lon": record["lon"],
            "last_update": record["last_update"],
            "predicted_aqi": round(aqi),
            "category": _category(round(aqi)),
            "dominant_pollutant": dominant_pollutant.upper(),
            "confidence": round(min(0.95, 0.55 + len(valid) * 0.06), 2),
            "model": "Live CPCB pollutant sub-index with satellite-ready feature contract",
            "source": record["source"],
            "sub_indices": {key.upper(): round(value) for key, value in valid.items()},
            **pollutants,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [record["lon"], record["lat"]]},
                "properties": props,
            }
        )
    return features


def _augment_with_interpolated_grid(station_features: list[dict]) -> dict:
    if not station_features:
        return {"features": [], "station_points": 0, "interpolated_points": 0}

    if os.getenv("AQI_INTERPOLATION_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "features": station_features,
            "station_points": len(station_features),
            "interpolated_points": 0,
        }

    lat_min = float(os.getenv("AQI_GRID_LAT_MIN", "6.0"))
    lat_max = float(os.getenv("AQI_GRID_LAT_MAX", "38.0"))
    lon_min = float(os.getenv("AQI_GRID_LON_MIN", "68.0"))
    lon_max = float(os.getenv("AQI_GRID_LON_MAX", "98.0"))
    step = max(0.35, float(os.getenv("AQI_GRID_STEP", "1.0")))
    max_cells = max(100, int(os.getenv("AQI_GRID_MAX_POINTS", "900")))
    search_radius_km = max(80.0, float(os.getenv("AQI_GRID_RADIUS_KM", "350")))
    near_station_km = max(20.0, float(os.getenv("AQI_GRID_NEAR_STATION_KM", "45")))
    k_neighbors = max(3, int(os.getenv("AQI_GRID_K_NEIGHBORS", "6")))

    station_points = []
    for feature in station_features:
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) != 2:
            continue
        lon, lat = coords
        aqi = props.get("predicted_aqi")
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and isinstance(aqi, (int, float))):
            continue
        station_points.append({
            "lat": float(lat),
            "lon": float(lon),
            "aqi": float(aqi),
            "confidence": float(props.get("confidence", 0.65)),
        })

    if len(station_points) < 3:
        return {
            "features": station_features,
            "station_points": len(station_features),
            "interpolated_points": 0,
        }

    interpolated_features = []
    lat = lat_min
    while lat <= lat_max:
        lon = lon_min
        while lon <= lon_max:
            if not _is_point_in_india(lat, lon):
                lon += step
                continue

            nearest_station_dist = min(_km(lat, lon, p["lat"], p["lon"]) for p in station_points)
            if nearest_station_dist <= near_station_km:
                lon += step
                continue

            candidates = []
            for point in station_points:
                dist = _km(lat, lon, point["lat"], point["lon"])
                if dist <= search_radius_km:
                    candidates.append((dist, point))
            candidates.sort(key=lambda item: item[0])
            candidates = candidates[:k_neighbors]

            if len(candidates) < 3:
                lon += step
                continue

            if not _has_directional_support(lat, lon, candidates):
                lon += step
                continue

            weighted_sum = 0.0
            weight_total = 0.0
            for dist, point in candidates:
                weight = (1.0 / ((dist + 1.0) ** 2)) * max(0.45, point["confidence"])
                weighted_sum += point["aqi"] * weight
                weight_total += weight

            if weight_total == 0:
                lon += step
                continue

            aqi = int(round(max(25, min(450, weighted_sum / weight_total))))
            interpolated_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(lon, 3), round(lat, 3)]},
                    "properties": {
                        "city": f"Grid cell {round(lat, 2)}N, {round(lon, 2)}E",
                        "station": "Interpolated",
                        "state": "India",
                        "lat": round(lat, 3),
                        "lon": round(lon, 3),
                        "predicted_aqi": aqi,
                        "category": _category(aqi),
                        "dominant_pollutant": "INTERPOLATED",
                        "confidence": round(max(0.35, min(0.78, 0.5 + (len(candidates) - 3) * 0.05)), 2),
                        "model": "IDW interpolation over nearby live CPCB stations",
                        "source": "derived_grid",
                        "interpolated": True,
                    },
                }
            )
            lon += step
        lat += step

    if len(interpolated_features) > max_cells:
        interpolated_features = _even_sample_features(interpolated_features, max_cells)

    return {
        "features": station_features + interpolated_features,
        "station_points": len(station_features),
        "interpolated_points": len(interpolated_features),
    }


def _sub_index(pollutant: str, concentration: float) -> float | None:
    for low_c, high_c, low_i, high_i in BREAKPOINTS.get(pollutant, []):
        if low_c <= concentration <= high_c:
            return ((high_i - low_i) / (high_c - low_c)) * (concentration - low_c) + low_i
    return 500 if concentration > 0 else None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return radius * 2 * atan2(sqrt(a), sqrt(1 - a))


def _is_point_in_india(lat: float, lon: float) -> bool:
    if lat < 6.0 or lat > 37.5 or lon < 68.0 or lon > 98.5:
        return False

    # Rough polygons keep interpolation inside Indian landmass zones.
    mainland = [
        (68.1, 23.9), (68.7, 22.0), (69.2, 20.5), (70.2, 19.0), (71.5, 18.0),
        (72.7, 16.4), (72.9, 14.8), (73.8, 12.8), (74.8, 11.2), (76.2, 9.1),
        (77.9, 8.1), (79.3, 9.0), (80.7, 10.7), (81.9, 13.5), (83.1, 16.4),
        (84.3, 18.9), (85.8, 21.2), (87.2, 22.7), (88.2, 22.5), (88.9, 21.7),
        (89.4, 22.4), (88.7, 24.0), (88.3, 25.8), (88.1, 27.0), (87.4, 28.3),
        (85.9, 28.2), (84.0, 27.0), (82.0, 28.0), (80.0, 29.6), (78.0, 31.1),
        (76.0, 32.6), (74.0, 34.1), (72.3, 35.2), (70.7, 34.7), (69.4, 33.3),
        (68.4, 30.8), (68.0, 27.5), (68.1, 23.9),
    ]

    northeast = [
        (88.0, 26.0), (89.2, 25.9), (90.4, 26.2), (91.5, 26.4), (92.8, 26.7),
        (94.0, 27.3), (95.2, 27.6), (96.1, 28.4), (97.1, 28.1), (97.4, 27.0),
        (96.6, 25.8), (95.6, 24.7), (94.4, 24.0), (93.1, 24.2), (91.7, 24.4),
        (90.1, 24.5), (89.0, 24.7), (88.1, 25.2), (88.0, 26.0),
    ]

    andaman = [
        (92.0, 13.8), (93.0, 13.8), (93.0, 6.2), (92.0, 6.2), (92.0, 13.8),
    ]

    lakshadweep = [
        (71.5, 12.8), (73.0, 12.8), (73.0, 9.0), (71.5, 9.0), (71.5, 12.8),
    ]

    return (
        _point_in_polygon(lat, lon, mainland)
        or _point_in_polygon(lat, lon, northeast)
        or _point_in_polygon(lat, lon, andaman)
        or _point_in_polygon(lat, lon, lakshadweep)
    )


def _point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) + 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def _has_directional_support(lat: float, lon: float, candidates: list[tuple[float, dict]]) -> bool:
    has_north = False
    has_south = False
    has_east = False
    has_west = False
    for _, point in candidates:
        if point["lat"] >= lat:
            has_north = True
        if point["lat"] <= lat:
            has_south = True
        if point["lon"] >= lon:
            has_east = True
        if point["lon"] <= lon:
            has_west = True
    # Prevent one-sided interpolation (common offshore/coastal artifact).
    return has_north and has_south and has_east and has_west


def _even_sample_features(features: list[dict], limit: int) -> list[dict]:
    if limit <= 0 or len(features) <= limit:
        return features
    selected = []
    total = len(features)
    for i in range(limit):
        idx = round(i * (total - 1) / (limit - 1)) if limit > 1 else 0
        selected.append(features[idx])
    return selected
