from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime, timedelta, timezone as _tz
import time
from threading import Lock
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from urllib.request import Request, urlopen

CPCB_RESOURCE_ID = "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
CPCB_API_URL = f"https://api.data.gov.in/resource/{CPCB_RESOURCE_ID}"
FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
INDIA_BOUNDS = "68.0,6.0,98.0,38.5"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_ENV_LOADED = False
_GEE_INITIALIZED = False
_LIVE_CACHE: dict = {}
_LIVE_CACHE_TTL = 3600   # per-fetcher cache: 1 hour (GEE / Open-Meteo)
_BUNDLE_CACHE: dict = {}
_BUNDLE_TTL = 300         # full bundle cache: 5 minutes
_BUNDLE_LOCK = Lock()

# Cities used for Open-Meteo meteorology fetch (free, no auth)
INDIA_MET_STATIONS = [
    ("Delhi",     28.61, 77.20),
    ("Gurugram",  28.46, 77.03),
    ("Ludhiana",  30.90, 75.86),
    ("Mumbai",    19.07, 72.88),
    ("Kolkata",   22.57, 88.36),
    ("Bengaluru", 12.97, 77.59),
    ("Hyderabad", 17.38, 78.49),
    ("Chennai",   13.08, 80.27),
    ("Ahmedabad", 23.02, 72.57),
    ("Lucknow",   26.85, 80.95),
]

DEFAULT_CPCB_TARGETS = [
    ("Delhi", "Delhi"),
    ("Haryana", "Gurugram"),
    ("Punjab", "Ludhiana"),
    ("Maharashtra", "Mumbai"),
    ("West_Bengal", "Kolkata"),
    ("Karnataka", "Bengaluru"),
    ("Telangana", "Hyderabad"),
    ("Tamil_Nadu", "Chennai"),
    ("Gujarat", "Ahmedabad"),
    ("Uttar_Pradesh", "Lucknow"),
]

CITY_COORDS = {
    "Delhi": (28.61, 77.2),
    "New Delhi": (28.61, 77.2),
    "Gurugram": (28.46, 77.03),
    "Ludhiana": (30.9, 75.86),
    "Mumbai": (19.07, 72.88),
    "Kolkata": (22.57, 88.36),
    "Bengaluru": (12.97, 77.59),
    "Bangalore": (12.97, 77.59),
    "Hyderabad": (17.38, 78.49),
    "Chennai": (13.08, 80.27),
    "Ahmedabad": (23.02, 72.57),
    "Lucknow": (26.85, 80.95),
}

POLLUTANT_KEYS = {
    "PM2.5": "pm25",
    "PM10": "pm10",
    "NO2": "no2",
    "SO2": "so2",
    "CO": "co",
    "OZONE": "o3",
    "O3": "o3",
    "NH3": "nh3",
    "HCHO": "hcho",
}


def live_bundle() -> dict:
    """
    Fetch all live data sources and return a unified bundle.

    Caching:
    - Full bundle is cached for 5 minutes (_BUNDLE_TTL).
    - Individual satellite fetchers (GEE / Open-Meteo) have their own 1-hour cache.

    Parallelism:
    - CPCB, FIRMS, TROPOMI, and Open-Meteo are all fetched concurrently via a
      thread pool, so the wall-clock time ≈ the slowest single fetcher, not the sum.
    """
    _load_env_file_once()

    # ── 5-minute bundle cache (first check outside lock for fast path) ───────
    cached_bundle = _BUNDLE_CACHE.get("bundle")
    if cached_bundle and time.time() - cached_bundle["ts"] < _BUNDLE_TTL:
        return cached_bundle["data"]

    with _BUNDLE_LOCK:
        # Re-check inside lock to prevent concurrent cold-start fetch storms.
        cached_bundle = _BUNDLE_CACHE.get("bundle")
        if cached_bundle and time.time() - cached_bundle["ts"] < _BUNDLE_TTL:
            return cached_bundle["data"]

        # ── Parallel fetch ────────────────────────────────────────────────────
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_cpcb    = pool.submit(fetch_cpcb_latest)
            f_firms   = pool.submit(fetch_firms_fire_points)
            f_tropomi = pool.submit(fetch_tropomi_hcho_gee)
            f_met     = pool.submit(fetch_openmeteo_met)

        cpcb    = f_cpcb.result()
        firms   = f_firms.result()
        tropomi = f_tropomi.result()
        met     = f_met.result()

        bundle = {
            "generated_at": datetime.now(UTC).isoformat(),
            "sources": [
                cpcb["status"],
                firms["status"],
                {k: v for k, v in tropomi.items() if k != "hcho_grid"},
                {k: v for k, v in met.items()     if k != "met_grid"},
                insat_status(),
            ],
            "cpcb_records": cpcb["records"],
            "fire_points":  firms["records"],
            "hcho_grid":    tropomi.get("hcho_grid", []),
            "met_grid":     met.get("met_grid", []),
        }
        _BUNDLE_CACHE["bundle"] = {"ts": time.time(), "data": bundle}
        return bundle


def fetch_cpcb_latest() -> dict:
    _load_env_file_once()
    api_key = os.getenv("DATA_GOV_API_KEY")
    if not api_key:
        return _missing("cpcb_caaqm", "Set DATA_GOV_API_KEY from data.gov.in to fetch CPCB real-time AQI records.")

    scope = os.getenv("CPCB_FETCH_SCOPE", "india").strip().lower()
    page_size = max(100, min(1000, int(os.getenv("CPCB_PAGE_SIZE", "1000"))))
    max_records = max(page_size, int(os.getenv("CPCB_MAX_RECORDS", "8000")))
    max_pages = max(1, (max_records + page_size - 1) // page_size)

    if scope != "targets":
        rows: list = []
        page_count = 0
        fetch_error: str | None = None
        for page in range(max_pages):
            params = {
                "api-key": api_key,
                "format": "json",
                "limit": str(page_size),
                "offset": str(page * page_size),
            }
            payload, error = _get_json(CPCB_API_URL, params)
            if error:
                fetch_error = error
                break
            page_rows = payload.get("records", [])
            if not page_rows:
                break
            rows.extend(page_rows)
            page_count += 1
            if len(page_rows) < page_size:
                break
            if len(rows) >= max_records:
                rows = rows[:max_records]
                break

        stations = _group_cpcb_rows(rows)
        if stations:
            status = {
                "dataset_id": "cpcb_caaqm",
                "mode": "live",
                "records": len(stations),
                "message": (
                    f"Fetched CPCB real-time AQI records across India ({len(rows)} rows, {len(stations)} stations, {page_count} pages)."
                ),
            }
            return {"status": status, "records": stations}

        if fetch_error:
            # Fall back to legacy target-city fetch path if nationwide pagination fails.
            fallback_note = f"India-wide fetch failed: {fetch_error}. Falling back to configured target cities."
        else:
            fallback_note = "India-wide fetch returned no usable stations. Falling back to configured target cities."
    else:
        fallback_note = "Using CPCB target-city scope from CPCB_FETCH_SCOPE=targets."

    def _fetch_city(state: str, city: str) -> tuple[list, str | None]:
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": "1000",
            "offset": "0",
            "filters[state]": state,
            "filters[city]": city,
        }
        payload, error = _get_json(CPCB_API_URL, params)
        if error:
            return [], f"{city}: {error}"
        return payload.get("records", []), None

    # Fetch all cities in parallel (10 cities × ~1–2 s each → total ~2 s instead of ~20 s)
    rows: list = []
    errors: list = []
    pairs = _target_city_pairs()
    with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures = {pool.submit(_fetch_city, state, city): city for state, city in pairs}
        for future, city in futures.items():
            city_rows, err = future.result()
            if err:
                errors.append(err)
            else:
                rows.extend(city_rows)

    stations = _group_cpcb_rows(rows)
    status = {
        "dataset_id": "cpcb_caaqm",
        "mode": "live" if stations else "unavailable",
        "records": len(stations),
        "message": (
            f"{fallback_note} Fetched CPCB target-city AQI records ({len(stations)} stations)." if stations
            else f"{fallback_note} " + ("; ".join(errors) or "No CPCB records returned.")
        ),
    }
    return {"status": status, "records": stations}


def fetch_firms_fire_points() -> dict:
    _load_env_file_once()
    map_key = os.getenv("FIRMS_MAP_KEY")
    if not map_key:
        return _missing("firms_fire", "Set FIRMS_MAP_KEY from NASA FIRMS to fetch near-real-time MODIS/VIIRS fire detections.")

    source = os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT")
    url = f"{FIRMS_AREA_URL}/{map_key}/{source}/{INDIA_BOUNDS}/1"
    text, error = _get_text(url)
    if error:
        return {"status": {"dataset_id": "firms_fire", "mode": "unavailable", "records": 0, "message": error}, "records": []}

    records = []
    for row in csv.DictReader(StringIO(text)):
        try:
            records.append(
                {
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "frp": float(row.get("frp") or 0),
                    "confidence": row.get("confidence", ""),
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "source": source,
                }
            )
        except (KeyError, ValueError):
            continue
    return {
        "status": {
            "dataset_id": "firms_fire",
            "mode": "live" if records else "unavailable",
            "records": len(records),
            "message": f"Fetched NASA FIRMS {source} detections for India." if records else "FIRMS returned no detections.",
        },
        "records": records,
    }


def _cache_get(key: str):
    entry = _LIVE_CACHE.get(key)
    if entry and time.time() - entry["ts"] < _LIVE_CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: dict) -> None:
    _LIVE_CACHE[key] = {"ts": time.time(), "data": data}


def fetch_tropomi_hcho_gee() -> dict:
    """Fetch TROPOMI HCHO grid via Google Earth Engine (cached 1 h)."""
    global _GEE_INITIALIZED
    cached = _cache_get("tropomi")
    if cached is not None:
        return cached

    project = os.getenv("GEE_PROJECT", "").strip()
    if not project:
        return {
            "dataset_id": "sentinel5p_tropomi", "mode": "unavailable", "records": 0,
            "message": "Set GEE_PROJECT in .env to enable TROPOMI HCHO via Google Earth Engine.",
            "hcho_grid": [],
        }

    try:
        import ee  # type: ignore[import]
    except ImportError:
        return {
            "dataset_id": "sentinel5p_tropomi", "mode": "unavailable", "records": 0,
            "message": "Install earthengine-api: pip install earthengine-api",
            "hcho_grid": [],
        }

    try:
        if not _GEE_INITIALIZED:
            ee.Initialize(project=project)
            _GEE_INITIALIZED = True

        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=5)  # OFFL product has ~3-5 day latency

        collection = (
            ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_HCHO")
            .filterDate(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            .select("tropospheric_HCHO_column_number_density")
        )
        image = ee.Image(collection.sort("system:time_start", False).first())
        india = ee.Geometry.Rectangle([68.0, 6.0, 98.0, 37.0])

        points = image.sample(region=india, scale=55000, numPixels=400, geometries=True, seed=42)

        # getInfo() is synchronous and can hang — enforce a 25-second hard timeout
        with ThreadPoolExecutor(max_workers=1) as _pool:
            _future = _pool.submit(points.getInfo)
            try:
                result_info = _future.result(timeout=25)
            except _FutureTimeout:
                _GEE_INITIALIZED = False
                return {
                    "dataset_id": "sentinel5p_tropomi", "mode": "unavailable", "records": 0,
                    "message": "GEE request timed out (>25 s). Will retry on next refresh.",
                    "hcho_grid": [],
                }
        features = result_info.get("features", [])

        grid = []
        for f in features:
            val = f["properties"].get("tropospheric_HCHO_column_number_density")
            if val is not None and val > 0:
                coords = f["geometry"]["coordinates"]
                grid.append({"lon": round(coords[0], 3), "lat": round(coords[1], 3), "hcho": round(val, 8)})

        result = {
            "dataset_id": "sentinel5p_tropomi",
            "mode": "live" if grid else "unavailable",
            "records": len(grid),
            "message": (
                f"Fetched {len(grid)} TROPOMI HCHO grid points via GEE." if grid
                else "No TROPOMI HCHO data available in date range."
            ),
            "hcho_grid": grid,
        }
        _cache_set("tropomi", result)
        return result

    except Exception as exc:
        _GEE_INITIALIZED = False  # Reset so next call retries
        return {
            "dataset_id": "sentinel5p_tropomi", "mode": "unavailable", "records": 0,
            "message": (
                f"GEE error: {exc}. "
                f"If first-time setup, run: earthengine authenticate --project {project}"
            ),
            "hcho_grid": [],
        }


def fetch_openmeteo_met() -> dict:
    """Fetch live meteorology from Open-Meteo (free, no API key required, cached 1 h)."""
    cached = _cache_get("openmeteo")
    if cached is not None:
        return cached

    lat_str = ",".join(str(lat) for _, lat, _ in INDIA_MET_STATIONS)
    lon_str = ",".join(str(lon) for _, _, lon in INDIA_MET_STATIONS)
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat_str}&longitude={lon_str}"
        f"&hourly=wind_speed_10m,wind_direction_10m,relative_humidity_2m,temperature_2m"
        f"&forecast_days=1&timezone=Asia%2FKolkata&models=best_match"
    )

    text, error = _get_text(url)
    if error:
        return {
            "dataset_id": "reanalysis_met", "mode": "unavailable", "records": 0,
            "message": f"Open-Meteo error: {error}", "met_grid": [],
        }

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            data = [data]

        # Find the index closest to the current IST hour
        IST = _tz(timedelta(hours=5, minutes=30))
        now_hour = datetime.now(IST).strftime("%Y-%m-%dT%H:00")

        records = []
        for i, loc_data in enumerate(data):
            if i >= len(INDIA_MET_STATIONS):
                break
            name, lat, lon = INDIA_MET_STATIONS[i]
            hourly = loc_data.get("hourly", {})
            times = hourly.get("time", [])
            if not times:
                continue
            idx = times.index(now_hour) if now_hour in times else -1
            records.append({
                "city": name, "lat": lat, "lon": lon,
                "wind_speed":    hourly.get("wind_speed_10m",      [None])[idx],
                "wind_dir":      hourly.get("wind_direction_10m",  [None])[idx],
                "humidity":      hourly.get("relative_humidity_2m",[None])[idx],
                "temperature":   hourly.get("temperature_2m",      [None])[idx],
            })

        result = {
            "dataset_id": "reanalysis_met",
            "mode": "live" if records else "unavailable",
            "records": len(records),
            "message": (
                f"Fetched live met data for {len(records)} cities via Open-Meteo (no auth required)."
                if records else "Open-Meteo returned no data."
            ),
            "met_grid": records,
        }
        _cache_set("openmeteo", result)
        return result

    except Exception as exc:
        return {
            "dataset_id": "reanalysis_met", "mode": "unavailable", "records": 0,
            "message": f"Open-Meteo parse error: {exc}", "met_grid": [],
        }


def tropomi_status() -> dict:
    result = fetch_tropomi_hcho_gee()
    return {k: v for k, v in result.items() if k != "hcho_grid"}


def reanalysis_status() -> dict:
    result = fetch_openmeteo_met()
    return {k: v for k, v in result.items() if k != "met_grid"}


def insat_status() -> dict:
    return {
        "dataset_id": "insat3d_aod",
        "mode": "unavailable",
        "records": 0,
        "message": (
            "INSAT-3D AOD not connected. "
            "MOSDAC authenticated download is required — set MOSDAC_TOKEN in .env to enable."
        ),
    }


def _target_city_pairs() -> list[tuple[str, str]]:
    raw = os.getenv("CPCB_TARGETS")
    if not raw:
        return DEFAULT_CPCB_TARGETS
    pairs = []
    for item in raw.split(";"):
        if "," not in item:
            continue
        state, city = [part.strip().replace(" ", "_") for part in item.split(",", 1)]
        pairs.append((state, city))
    return pairs or DEFAULT_CPCB_TARGETS


def _load_env_file_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"]:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _group_cpcb_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        city = _clean(row.get("city"))
        station = _clean(row.get("station"))
        pollutant = _clean(row.get("pollutant_id")).upper()
        key = POLLUTANT_KEYS.get(pollutant)
        if not city or not station or not key:
            continue
        # API field is "avg_value", not "pollutant_avg"
        value = _to_float(row.get("avg_value") or row.get("pollutant_avg"))
        if value is None:
            continue
        station_key = (_clean(row.get("state")), city, station)
        # Prefer per-station coordinates from the API; fall back to city-level lookup
        api_lat = _to_float(row.get("latitude"))
        api_lon = _to_float(row.get("longitude"))
        if api_lat is not None and api_lon is not None:
            lat, lon = api_lat, api_lon
        else:
            lat, lon = CITY_COORDS.get(city, CITY_COORDS.get(city.replace("_", " "), (22.8, 80.5)))
        item = grouped.setdefault(
            station_key,
            {
                "state": _clean(row.get("state")),
                "city": city.replace("_", " "),
                "station": station,
                "lat": lat,
                "lon": lon,
                "last_update": _clean(row.get("last_update")),
                "source": "CPCB real-time AQI via data.gov.in",
                "pollutants": {},
            },
        )
        item["pollutants"][key] = value
    return list(grouped.values())


def _get_json(url: str, params: dict) -> tuple[dict, str | None]:
    text, error = _get_text(f"{url}?{urlencode(params)}")
    if error:
        return {}, error
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON response: {exc}"


def _get_text(url: str) -> tuple[str, str | None]:
    try:
        request = Request(url, headers={"User-Agent": "AkashChalak-SIH-Prototype/0.1"})
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace"), None
    except HTTPError as exc:
        return "", f"HTTP {exc.code}: {exc.reason}"
    except URLError as exc:
        return "", f"Network error: {exc.reason}"
    except TimeoutError:
        return "", "Request timed out"


def _missing(dataset_id: str, message: str) -> dict:
    return {"status": {"dataset_id": dataset_id, "mode": "missing_credentials", "records": 0, "message": message}, "records": []}


def _clean(value) -> str:
    return str(value or "").strip()


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
