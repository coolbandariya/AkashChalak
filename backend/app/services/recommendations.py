def build_recommendations(aqi_features: list[dict], hotspot_features: list[dict]) -> list[dict]:
    high_aqi = sorted(
        [item["properties"] for item in aqi_features if item["properties"]["predicted_aqi"] >= 150],
        key=lambda item: item["predicted_aqi"],
        reverse=True,
    )
    recommendations = []
    for item in high_aqi[:5]:
        action = "Issue public health advisory and increase mobile monitoring."
        if item.get("fire_count", 0) >= 12:
            action = "Prioritize fire-source verification, enforcement, and downwind health advisory."
        elif item.get("dominant_pollutant") == "NO2" or item.get("no2", 0) > 0.00011:
            action = "Review traffic and industrial NO2 controls for the urban airshed."
        elif item.get("dominant_pollutant") in {"PM25", "PM10"}:
            action = "Deploy road-dust suppression, restrict open burning, and intensify construction dust checks."
        recommendations.append(
            {
                "region": item["city"],
                "severity": item["category"],
                "predicted_aqi": item["predicted_aqi"],
                "drivers": _drivers(item),
                "action": action,
            }
        )

    for hotspot in hotspot_features:
        props = hotspot["properties"]
        recommendations.append(
            {
                "region": ", ".join(props["locations"]),
                "severity": "HCHO hotspot",
                "predicted_aqi": None,
                "drivers": ["HCHO anomaly", "fire detections", "wind transport"],
                "action": "Track plume movement for the next forecast cycle and notify affected districts.",
            }
        )
    return recommendations


def _drivers(item: dict) -> list[str]:
    drivers = []
    if item.get("dominant_pollutant"):
        drivers.append(f"dominant {item['dominant_pollutant']}")
    if item.get("aod", 0) >= 0.65:
        drivers.append("high AOD")
    if item.get("fire_count", 0) >= 12:
        drivers.append("active fires")
    if item.get("hcho", 0) >= 0.00014 or item.get("hcho", 0) >= 20:
        drivers.append("HCHO anomaly")
    if item.get("wind_speed", 99) <= 2.5:
        drivers.append("low wind dispersion")
    return drivers or ["multi-source satellite signal"]
