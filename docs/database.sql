CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS aqi_observations (
  id BIGSERIAL PRIMARY KEY,
  observed_at TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL,
  city TEXT NOT NULL,
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  aod DOUBLE PRECISION,
  no2 DOUBLE PRECISION,
  so2 DOUBLE PRECISION,
  co DOUBLE PRECISION,
  o3 DOUBLE PRECISION,
  hcho DOUBLE PRECISION,
  fire_count DOUBLE PRECISION,
  u10 DOUBLE PRECISION,
  v10 DOUBLE PRECISION,
  surface_aqi DOUBLE PRECISION
);

SELECT create_hypertable('aqi_observations', 'observed_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_aqi_observations_city_time ON aqi_observations (city, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_aqi_observations_location ON aqi_observations (lat, lon);
