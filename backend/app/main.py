from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.services.action_plan import build_action_plan
from app.services.aqi_model import predict_surface_aqi
from app.services.datasets import DATASETS
from app.services.hotspots import detect_hcho_hotspots
from app.services.ingestion import ingestion_plan
from app.services.recommendations import build_recommendations

app = FastAPI(
    title="AkashChalak Surface AQI API",
    description="Satellite-assisted AQI prediction and HCHO hotspot detection prototype.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "akashchalak-api",
        "model_mode": "tensorflow-ready fallback",
        "storage": "postgresql-timescaledb-ready",
    }


@app.get("/api/datasets")
def datasets() -> list[dict]:
    return DATASETS


@app.get("/api/live/status")
def live_status() -> dict:
    aqi = predict_surface_aqi()
    return {"mode": aqi["mode"], "sources": aqi["sources"]}


@app.get("/api/ingestion/plan")
def ingestion() -> list[dict]:
    return ingestion_plan()


@app.get("/api/aqi/grid")
def aqi_grid() -> dict:
    predictions = predict_surface_aqi()
    return {
        "type": "FeatureCollection",
        "mode": predictions["mode"],
        "sources": predictions["sources"],
        "summary": predictions.get("summary", {}),
        "generated_from": [
            "INSAT-3D AOD",
            "Sentinel-5P TROPOMI NO2/SO2/CO/O3/HCHO",
            "CPCB CAAQM",
            "MODIS/VIIRS FIRMS fire count",
            "ERA5/IMDAA/MERRA-2 meteorology",
        ],
        "features": predictions["features"],
    }


@app.get("/api/hotspots")
def hotspots() -> dict:
    clusters = detect_hcho_hotspots()
    return {
        "type": "FeatureCollection",
        "mode": clusters["mode"],
        "sources": clusters["sources"],
        "summary": clusters.get("summary", {}),
        "method": "DBSCAN over HCHO anomaly, fire density, and wind-aligned transport features",
        "features": clusters["features"],
    }


@app.get("/api/recommendations")
def recommendations() -> list[dict]:
    aqi = predict_surface_aqi()
    hotspots_payload = detect_hcho_hotspots()
    return build_recommendations(aqi["features"], hotspots_payload["features"])


@app.get("/api/action-plan")
def action_plan() -> dict:
    aqi = predict_surface_aqi()
    hotspots_payload = detect_hcho_hotspots()
    return build_action_plan(aqi["features"], hotspots_payload["features"])


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent.parent / "frontend"

if not FRONTEND_DIR.exists():
    FRONTEND_DIR = BASE_DIR.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")