def build_action_plan(aqi_features: list[dict], hotspot_features: list[dict]) -> dict:
    if not aqi_features and not hotspot_features:
        return {
            "status": "waiting_for_live_data",
            "summary": "No action plan can be generated until live CPCB AQI and hotspot inputs are available.",
            "steps": [
                {
                    "region": "System",
                    "priority": "setup",
                    "timeframe": "Before launch",
                    "step": "Set DATA_GOV_API_KEY for live CPCB AQI.",
                    "trigger": "CPCB credentials are missing.",
                },
                {
                    "region": "System",
                    "priority": "setup",
                    "timeframe": "Before launch",
                    "step": "Set FIRMS_MAP_KEY for live MODIS/VIIRS fire detections.",
                    "trigger": "NASA FIRMS credentials are missing.",
                },
                {
                    "region": "System",
                    "priority": "setup",
                    "timeframe": "Before launch",
                    "step": "Add Sentinel-5P HCHO feed through Earth Engine export or TROPOMI_HCHO_GEOJSON_URL.",
                    "trigger": "Live gridded HCHO feed is not configured.",
                },
            ],
        }

    worst = sorted(aqi_features, key=lambda feature: feature["properties"].get("predicted_aqi", 0), reverse=True)[:5]
    hotspots = [feature["properties"] for feature in hotspot_features]
    steps = []

    for feature in worst:
        props = feature["properties"]
        region = f"{props.get('city', 'Unknown')} - {props.get('station', 'station')}"
        dominant = props.get("dominant_pollutant", "AQI")
        aqi = props.get("predicted_aqi")
        steps.extend(_aqi_steps(region, aqi, dominant))

    for hotspot in hotspots:
        region = ", ".join(hotspot.get("locations", []))
        steps.append(
            {
                "region": region,
                "priority": "hotspot",
                "timeframe": "0-12 hours",
                "step": "Verify fire or industrial source, map downwind exposure, and notify district officials in the plume path.",
                "trigger": f"HCHO {hotspot.get('mean_hcho')} with {hotspot.get('fire_count')} nearby fire detections.",
            }
        )

    return {
        "status": "generated",
        "summary": "Action plan generated from live AQI stations and HCHO/fire hotspot clusters.",
        "steps": steps[:18],
    }


def _aqi_steps(region: str, aqi: int, dominant: str) -> list[dict]:
    if aqi >= 301:
        priority = "emergency"
        public_step = "Issue health advisory, suspend outdoor school activity, and activate emergency response room."
    elif aqi >= 201:
        priority = "high"
        public_step = "Advise masks for vulnerable groups, reduce outdoor exposure, and increase field inspections."
    elif aqi >= 101:
        priority = "moderate"
        public_step = "Publish local advisory and inspect known dust, traffic, and burning sources."
    else:
        priority = "watch"
        public_step = "Continue monitoring and keep source-control teams on standby."

    source_step = _source_step(dominant)
    return [
        {"region": region, "priority": priority, "timeframe": "0-6 hours", "step": public_step, "trigger": f"AQI {aqi}, dominant pollutant {dominant}."},
        {"region": region, "priority": priority, "timeframe": "6-24 hours", "step": source_step, "trigger": f"Dominant pollutant {dominant}."},
        {
            "region": region,
            "priority": priority,
            "timeframe": "24-72 hours",
            "step": "Compare next two update cycles; continue controls only where AQI stays elevated to avoid blanket restrictions.",
            "trigger": "Persistent live AQI elevation.",
        },
    ]


def _source_step(dominant: str) -> str:
    if dominant in {"PM25", "PM2.5", "PM10"}:
        return "Suppress road and construction dust, restrict open burning, and check industrial stack compliance."
    if dominant == "NO2":
        return "Reduce traffic congestion near hotspots, inspect diesel generators, and target high-emission corridors."
    if dominant == "SO2":
        return "Inspect fuel quality and industrial sulfur controls around the affected airshed."
    if dominant == "CO":
        return "Check combustion sources, traffic choke points, and generator usage in the affected area."
    if dominant in {"O3", "OZONE"}:
        return "Reduce precursor emissions from traffic and solvent sources during high-sunlight hours."
    return "Dispatch field team to identify local emission sources and validate station readings."
