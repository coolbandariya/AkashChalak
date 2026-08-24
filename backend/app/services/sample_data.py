from __future__ import annotations

import math
import random

RANDOM_SEED = 20260824

CITY_ANCHORS = [
    ("Delhi NCR", 28.61, 77.20, 215),
    ("Punjab-Haryana belt", 30.75, 76.78, 190),
    ("Mumbai", 19.07, 72.88, 118),
    ("Kolkata", 22.57, 88.36, 162),
    ("Bengaluru", 12.97, 77.59, 74),
    ("Hyderabad", 17.38, 78.49, 92),
    ("Chennai", 13.08, 80.27, 86),
    ("Ahmedabad", 23.02, 72.57, 141),
    ("Lucknow", 26.85, 80.95, 176),
    ("Guwahati", 26.14, 91.74, 112),
    ("Raipur", 21.25, 81.63, 134),
    ("Bhopal", 23.26, 77.41, 104),
]


def build_observations() -> list[dict]:
    random.seed(RANDOM_SEED)
    observations: list[dict] = []
    for city, lat, lon, base_aqi in CITY_ANCHORS:
        fire_pressure = max(0, random.gauss(2.2 if "Punjab" in city or city == "Delhi NCR" else 0.8, 1.1))
        hcho = 0.00008 + fire_pressure * 0.000032 + random.random() * 0.00003
        aod = 0.35 + base_aqi / 550 + random.random() * 0.16
        no2 = 0.00005 + base_aqi / 2_700_000 + random.random() * 0.00003
        so2 = 0.000015 + random.random() * 0.000035
        co = 0.026 + base_aqi / 8500 + random.random() * 0.012
        o3 = 0.118 - base_aqi / 5000 + random.random() * 0.012
        wind_u = random.uniform(-4.2, 4.2)
        wind_v = random.uniform(-3.5, 3.5)
        humidity = random.uniform(38, 82)
        temp = random.uniform(291, 306)
        observations.append(
            {
                "city": city,
                "lat": round(lat, 3),
                "lon": round(lon, 3),
                "aod": round(aod, 3),
                "no2": round(no2, 8),
                "so2": round(so2, 8),
                "co": round(co, 5),
                "o3": round(o3, 5),
                "hcho": round(hcho, 8),
                "fire_count": round(fire_pressure * 6 + random.random() * 5, 1),
                "u10": round(wind_u, 2),
                "v10": round(wind_v, 2),
                "wind_speed": round(math.sqrt(wind_u**2 + wind_v**2), 2),
                "temperature": round(temp, 1),
                "relative_humidity": round(humidity, 1),
                "cpcb_station_aqi": base_aqi,
            }
        )
    return observations
