from __future__ import annotations

import os
from math import radians, sin, cos, sqrt, atan2
from statistics import mean

from app.services.live_sources import live_bundle
from app.services.sample_data import build_observations

try:
    from sklearn.cluster import DBSCAN
except Exception:  # pragma: no cover
    DBSCAN = None


def detect_hcho_hotspots() -> dict:
    bundle = live_bundle()
    features = _detect_from_live(
        bundle["cpcb_records"],
        bundle["fire_points"],
        bundle.get("hcho_grid", []),
        bundle.get("met_grid", []),
    )
    if features:
        return {
            "features": features,
            "sources": bundle["sources"],
            "mode": "live",
            "summary": _summarize_hotspots(features),
        }
    if os.getenv("ALLOW_DEMO_FALLBACK", "").lower() == "true":
        demo = _detect_from_demo()
        return {
            "features": demo,
            "sources": bundle["sources"],
            "mode": "demo_fallback",
            "summary": _summarize_hotspots(demo),
        }
    return {
        "features": [],
        "sources": bundle["sources"],
        "mode": "no_live_data",
        "summary": {"total": 0, "by_basis": {}},
    }


def _detect_from_demo() -> list[dict]:
    observations = build_observations()
    candidates = [row for row in observations if row["hcho"] >= 0.00014 or row["fire_count"] >= 12]
    if not candidates:
        return []

    if DBSCAN:
        matrix = [[row["lat"] * 0.8, row["lon"] * 0.8, row["hcho"] * 10000, row["fire_count"] / 10] for row in candidates]
        labels = DBSCAN(eps=2.0, min_samples=1).fit_predict(matrix)
    else:
        labels = list(range(len(candidates)))

    clusters = []
    for label in sorted(set(labels)):
        members = [row for row, row_label in zip(candidates, labels) if row_label == label]
        avg_lat = mean(row["lat"] for row in members)
        avg_lon = mean(row["lon"] for row in members)
        avg_hcho = mean(row["hcho"] for row in members)
        total_fires = sum(row["fire_count"] for row in members)
        wind_u = mean(row["u10"] for row in members)
        wind_v = mean(row["v10"] for row in members)
        confidence = min(0.96, 0.45 + avg_hcho * 2400 + total_fires / 80)
        clusters.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(avg_lon, 3), round(avg_lat, 3)]},
                "properties": {
                    "cluster_id": int(label),
                    "locations": [row["city"] for row in members],
                    "mean_hcho": round(avg_hcho, 8),
                    "fire_count": round(total_fires, 1),
                    "wind_u": round(wind_u, 2),
                    "wind_v": round(wind_v, 2),
                    "confidence": round(confidence, 2),
                    "likely_source": "biomass burning" if total_fires >= 18 else "mixed urban/industrial emissions",
                },
            }
        )
    return clusters


def _detect_from_live(
    cpcb_records: list[dict],
    fire_points: list[dict],
    hcho_grid: list[dict] | None = None,
    met_grid: list[dict] | None = None,
) -> list[dict]:
    """
    Detect HCHO hotspot clusters from live data.

    Strategy (in priority order):
    0. If GEE TROPOMI hcho_grid is available, cluster grid points above threshold directly.
    1. CPCB stations that report HCHO AND/OR have >=2 fires within 150 km qualify as candidates.
    2. If no CPCB-anchored candidates exist (CPCB rarely reports HCHO), fall back to
       clustering raw FIRMS fire points by FRP as a biomass-burning HCHO proxy.
    """
    threshold = float(os.getenv("HCHO_HOTSPOT_THRESHOLD", "20"))
    FIRE_RADIUS_KM = 150  # wider radius — fires 100-150 km upwind still affect AQI

    # ── Path 0: Real TROPOMI HCHO grid from GEE ───────────────────────────────
    # hcho values from GEE are in mol/m² (typical range 1e-4 to 5e-3)
    # We threshold at 5e-4 mol/m² (~500 DU equivalent) as "elevated"
    GEE_HCHO_THRESHOLD = 5e-4
    if hcho_grid:
        elevated = [pt for pt in hcho_grid if pt["hcho"] >= GEE_HCHO_THRESHOLD]
        if elevated and DBSCAN:
            matrix = [[pt["lat"], pt["lon"]] for pt in elevated]
            labels = DBSCAN(eps=1.5, min_samples=2).fit_predict(matrix)
        elif elevated:
            labels = list(range(len(elevated)))
        else:
            labels = []

        clusters = []
        for label in sorted(set(labels)):
            if label == -1:
                continue
            members = [pt for pt, lbl in zip(elevated, labels) if lbl == label]
            avg_hcho = mean(pt["hcho"] for pt in members)
            avg_lat = mean(pt["lat"] for pt in members)
            avg_lon = mean(pt["lon"] for pt in members)
            # Find FIRMS fires near this cluster centroid
            nearby_fires = [
                f for f in fire_points
                if _km(avg_lat, avg_lon, f["lat"], f["lon"]) <= FIRE_RADIUS_KM
            ]
            total_frp = sum(f["frp"] for f in nearby_fires)
            confidence = round(min(0.96, 0.55 + avg_hcho / 2e-3 + len(nearby_fires) * 0.02), 2)
            clusters.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(avg_lon, 3), round(avg_lat, 3)]},
                "properties": {
                    "cluster_id": int(label),
                    "locations": [f"TROPOMI grid ({round(avg_lat,1)}°N, {round(avg_lon,1)}°E)"],
                    "mean_hcho": round(avg_hcho, 8),
                    "hcho_proxy": round(avg_hcho * 1e6, 2),  # convert to µmol/m²
                    "fire_count": len(nearby_fires),
                    "frp": round(total_frp, 1),
                    "confidence": confidence,
                    "likely_source": "biomass burning" if len(nearby_fires) >= 3 else "industrial/urban HCHO",
                    "data_basis": "sentinel5p_tropomi_gee",
                },
            })
        if clusters:
            merged = _merge_with_fire_clusters(clusters, fire_points)
            return _attach_wind_vectors(merged, met_grid)

    # ── Path 1: CPCB-station-anchored candidates ──────────────────────────────
    candidates = []
    for record in cpcb_records:
        hcho = record["pollutants"].get("hcho")
        nearby_fires = [
            fire for fire in fire_points
            if _km(record["lat"], record["lon"], fire["lat"], fire["lon"]) <= FIRE_RADIUS_KM
        ]
        # Include if station has elevated HCHO OR >= 2 fires nearby
        if hcho is None and len(nearby_fires) < 2:
            continue
        if (hcho or 0) < threshold and len(nearby_fires) < 2:
            continue
        candidates.append({**record, "hcho": hcho or 0, "nearby_fires": nearby_fires})

    if candidates:
        if DBSCAN:
            matrix = [
                [row["lat"] * 0.8, row["lon"] * 0.8, row["hcho"] / 10, len(row["nearby_fires"])]
                for row in candidates
            ]
            labels = DBSCAN(eps=2.0, min_samples=1).fit_predict(matrix)
        else:
            labels = list(range(len(candidates)))

        clusters = []
        for label in sorted(set(labels)):
            members = [row for row, lbl in zip(candidates, labels) if lbl == label]
            fires = [fire for member in members for fire in member["nearby_fires"]]
            avg_hcho = mean(row["hcho"] for row in members)
            total_frp = sum(fire["frp"] for fire in fires)
            hcho_proxy = avg_hcho if avg_hcho > 0 else min(total_frp * 0.3, 500)
            clusters.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            round(mean(row["lon"] for row in members), 3),
                            round(mean(row["lat"] for row in members), 3),
                        ],
                    },
                    "properties": {
                        "cluster_id": int(label),
                        "locations": [f"{row['city']} - {row['station']}" for row in members],
                        "mean_hcho": round(avg_hcho, 2),
                        "hcho_proxy": round(hcho_proxy, 2),
                        "fire_count": len(fires),
                        "frp": round(total_frp, 1),
                        "confidence": round(
                            min(0.96, 0.45 + len(fires) * 0.04 + hcho_proxy / 200), 2
                        ),
                        "likely_source": (
                            "biomass burning" if len(fires) >= 3 else "observed HCHO anomaly"
                        ),
                        "data_basis": "cpcb_station",
                    },
                }
            )
        merged = _merge_with_fire_clusters(clusters, fire_points)
        return _attach_wind_vectors(merged, met_grid)

    # ── Path 2: FIRMS fire-point clusters (HCHO proxy via FRP) ────────────────
    # Group fire points into spatial clusters; each cluster with >= 2 detections
    # is flagged as a probable HCHO hotspot (biomass burning proxy).
    if not fire_points:
        return []

    return _attach_wind_vectors(_build_fire_proxy_clusters(fire_points), met_grid)


def _merge_with_fire_clusters(primary_clusters: list[dict], fire_points: list[dict]) -> list[dict]:
    if not fire_points:
        return primary_clusters

    supplementary = _build_fire_proxy_clusters(fire_points)
    if not supplementary:
        return primary_clusters

    merge_radius_km = float(os.getenv("HCHO_MERGE_RADIUS_KM", "130"))
    min_fire_count = int(os.getenv("HCHO_SUPPLEMENTARY_FIRE_MIN", "3"))
    merged = list(primary_clusters)

    for extra in supplementary:
        props = extra.get("properties", {})
        if props.get("fire_count", 0) < min_fire_count:
            continue
        lon, lat = extra["geometry"]["coordinates"]
        near_existing = False
        for base in merged:
            base_lon, base_lat = base["geometry"]["coordinates"]
            if _km(lat, lon, base_lat, base_lon) <= merge_radius_km:
                near_existing = True
                break
        if not near_existing:
            merged.append(extra)
    return merged


def _build_fire_proxy_clusters(fire_points: list[dict]) -> list[dict]:
    if not fire_points:
        return []

    eps = float(os.getenv("HCHO_FIRE_DBSCAN_EPS", "0.8"))
    min_samples = int(os.getenv("HCHO_FIRE_DBSCAN_MIN_SAMPLES", "2"))
    if DBSCAN:
        matrix = [[f["lat"], f["lon"]] for f in fire_points]
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(matrix)
    else:
        labels = list(range(len(fire_points)))

    clusters = []
    for label in sorted(set(labels)):
        if label == -1:  # DBSCAN noise label — skip isolated detections
            continue
        members = [f for f, lbl in zip(fire_points, labels) if lbl == label]
        total_frp = sum(f["frp"] for f in members)
        avg_lat = mean(f["lat"] for f in members)
        avg_lon = mean(f["lon"] for f in members)
        hcho_proxy = min(total_frp * 0.3, 500)
        confidence = round(min(0.90, 0.40 + len(members) * 0.03 + total_frp / 300), 2)
        clusters.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(avg_lon, 3), round(avg_lat, 3)],
                },
                "properties": {
                    "cluster_id": int(label),
                    "locations": list({f["source"] for f in members}),
                    "mean_hcho": 0.0,
                    "hcho_proxy": round(hcho_proxy, 2),
                    "fire_count": len(members),
                    "frp": round(total_frp, 1),
                    "confidence": confidence,
                    "likely_source": "biomass burning (FIRMS FRP proxy)",
                    "data_basis": "firms_fire_cluster",
                },
            }
        )
    return clusters


def _attach_wind_vectors(clusters: list[dict], met_grid: list[dict] | None) -> list[dict]:
    if not clusters or not met_grid:
        return clusters

    usable_met = []
    for met in met_grid:
        lat = _to_float(met.get("lat"))
        lon = _to_float(met.get("lon"))
        speed = _to_float(met.get("wind_speed"))
        direction = _to_float(met.get("wind_dir"))
        if lat is None or lon is None or speed is None or direction is None:
            continue
        usable_met.append({"lat": lat, "lon": lon, "wind_speed": speed, "wind_dir": direction})

    if not usable_met:
        return clusters

    for cluster in clusters:
        props = cluster.get("properties", {})
        if _to_float(props.get("wind_u")) is not None and _to_float(props.get("wind_v")) is not None:
            continue

        coords = cluster.get("geometry", {}).get("coordinates", [])
        if len(coords) != 2:
            continue
        lon, lat = coords

        nearest = min(usable_met, key=lambda met: _km(lat, lon, met["lat"], met["lon"]))
        speed = nearest["wind_speed"]
        direction = nearest["wind_dir"]

        theta = radians(direction)
        # Meteorological convention: wind direction is where wind comes from.
        # Convert to u/v so vectors indicate downwind transport direction.
        wind_u = -speed * sin(theta)
        wind_v = -speed * cos(theta)

        props["wind_u"] = round(wind_u, 2)
        props["wind_v"] = round(wind_v, 2)
        props["wind_speed"] = round(speed, 2)
        props["wind_dir"] = round(direction, 1)
        props["wind_source"] = "openmeteo_nearest"
        cluster["properties"] = props

    return clusters


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return radius * 2 * atan2(sqrt(a), sqrt(1 - a))


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_hotspots(features: list[dict]) -> dict:
    by_basis: dict[str, int] = {}
    for feature in features:
        basis = feature.get("properties", {}).get("data_basis", "unknown")
        by_basis[basis] = by_basis.get(basis, 0) + 1
    return {"total": len(features), "by_basis": by_basis}
