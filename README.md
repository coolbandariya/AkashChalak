# AkashChalak NAQI + HCHO Hotspot Prototype

Satellite-assisted air-quality decision support prototype for India.

Current build highlights:

- India-oriented NAQI map categories and legend labels.
- Live CPCB + FIRMS ingestion with graceful fallback behavior.
- India-wide NAQI interpolation (IDW) with India-only spatial mask.
- HCHO hotspots from TROPOMI/CPCB/fire clusters with wind-direction vectors.
- Single-command local startup using `run.py`.

## Tech Stack

- Python + FastAPI backend
- React + Leaflet frontend
- scikit-learn DBSCAN for hotspot clustering
- Deterministic NAQI fallback model (TensorFlow-ready integration path)
- Optional PostgreSQL/TimescaleDB support via Docker Compose

## Quick Start

Run everything (backend + frontend + browser open):

```powershell
python run.py
```

What `run.py` does:

- starts backend at `http://localhost:8000`
- starts frontend at `http://localhost:5173`
- opens the frontend in your default browser
- performs backend warm-up in the background
- stops both services on `Ctrl+C`

Manual mode (if you prefer separate terminals):

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
cd frontend
python -m http.server 5173
```

## Configuration

Create `.env` in the project root (or `backend/.env`) and set what you need.

Required for meaningful live outputs:

```text
DATA_GOV_API_KEY=your-data-gov-in-key
FIRMS_MAP_KEY=your-nasa-firms-map-key
```

Recommended current settings:

```text
CPCB_FETCH_SCOPE=india
AQI_GRID_STEP=1.25
AQI_GRID_MAX_POINTS=420
ALLOW_DEMO_FALLBACK=true
```

Optional live-source settings:

```text
FIRMS_SOURCE=VIIRS_SNPP_NRT
HCHO_HOTSPOT_THRESHOLD=20
GEE_PROJECT=your-google-earth-engine-project
```

### CPCB Coverage Controls

- `CPCB_FETCH_SCOPE`: `india` (default) or `targets`
- `CPCB_PAGE_SIZE`: API page size (100 to 1000)
- `CPCB_MAX_RECORDS`: max rows fetched across pages
- `CPCB_TARGETS`: used when scope is `targets`

### NAQI Interpolation Controls

- `AQI_INTERPOLATION_ENABLED`: `true` or `false`
- `AQI_GRID_STEP`: grid spacing in degrees (smaller = denser)
- `AQI_GRID_MAX_POINTS`: cap on interpolated points
- `AQI_GRID_RADIUS_KM`: neighbor search radius
- `AQI_GRID_NEAR_STATION_KM`: skip interpolation very close to stations
- `AQI_GRID_K_NEIGHBORS`: number of nearest stations for IDW
- `AQI_GRID_LAT_MIN`, `AQI_GRID_LAT_MAX`, `AQI_GRID_LON_MIN`, `AQI_GRID_LON_MAX`: override bounds if needed

Interpolation logic includes:

- India-only geographic masking
- directional support checks to reduce coastal/offshore artifacts
- even spatial sampling when raw candidate count exceeds `AQI_GRID_MAX_POINTS`

### HCHO Hotspot Controls

- `HCHO_HOTSPOT_THRESHOLD`: CPCB HCHO threshold gate
- `HCHO_FIRE_DBSCAN_EPS`: DBSCAN radius for fire clustering
- `HCHO_FIRE_DBSCAN_MIN_SAMPLES`: DBSCAN min samples
- `HCHO_SUPPLEMENTARY_FIRE_MIN`: minimum fire count for supplementary clusters
- `HCHO_MERGE_RADIUS_KM`: merge radius when combining primary and supplementary clusters

Hotspot wind vectors:

- if a hotspot has no native `wind_u/wind_v`, nearest Open-Meteo wind is attached
- frontend arrows then render for all hotspot types consistently

## API Endpoints

- `GET /api/health`
- `GET /api/datasets`
- `GET /api/ingestion/plan`
- `GET /api/live/status`
- `GET /api/aqi/grid`
- `GET /api/hotspots`
- `GET /api/recommendations`
- `GET /api/action-plan`

### Response Additions

- `/api/aqi/grid` includes `summary`:
  - `station_points`
  - `interpolated_points`
  - `total_points`

- `/api/hotspots` includes `summary`:
  - `total`
  - `by_basis` (for example `cpcb_station`, `firms_fire_cluster`, `sentinel5p_tropomi_gee`)

## NAQI vs AQI Note

User-facing dashboard labels use **NAQI** terminology and CPCB-style category bands:

- Good: 0 to 50
- Satisfactory: 51 to 100
- Moderate: 101 to 200
- Poor: 201 to 300
- Very Poor: 301 to 400
- Severe: 401 to 500

## Optional TimescaleDB

```powershell
docker compose up -d timescaledb
```

Then set:

```powershell
$env:DATABASE_URL="postgresql+psycopg://akash:akash@localhost:5432/akashchalak"
```

The prototype runs without a database in local mode.
