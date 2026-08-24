from __future__ import annotations

import os

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

metadata = MetaData()

aqi_observations = Table(
    "aqi_observations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("observed_at", DateTime, nullable=False),
    Column("source", String(80), nullable=False),
    Column("city", String(120), nullable=False),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("aod", Float),
    Column("no2", Float),
    Column("so2", Float),
    Column("co", Float),
    Column("o3", Float),
    Column("hcho", Float),
    Column("fire_count", Float),
    Column("u10", Float),
    Column("v10", Float),
    Column("surface_aqi", Float),
)


def get_engine():
    return create_engine(DATABASE_URL, future=True)
