from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionConnector:
    dataset_id: str
    expected_format: str
    auth_required: bool
    spatial_step: str
    temporal_step: str


CONNECTORS = [
    IngestionConnector("insat3d_aod", "HDF / gridded raster", True, "regrid to India 0.1 degree cells", "daily composite"),
    IngestionConnector("sentinel5p_tropomi", "NetCDF / Earth Engine image collection", False, "clip to India and resample", "daily composite"),
    IngestionConnector("cpcb_caaqm", "CSV export / repository download", False, "station to grid join", "hourly aggregation"),
    IngestionConnector("firms_fire", "CSV / GeoJSON active fire points", True, "point density by grid cell", "daily count and FRP sum"),
    IngestionConnector("reanalysis_met", "NetCDF / GRIB", True, "bilinear interpolation to AQI grid", "hourly features"),
]


def ingestion_plan() -> list[dict]:
    return [connector.__dict__ for connector in CONNECTORS]
