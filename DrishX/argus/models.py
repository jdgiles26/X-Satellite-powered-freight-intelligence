"""
ARGUS SQLAlchemy Models
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, String, Float, DateTime, Integer,
    JSON, Text, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID

from argus.database import Base


class Mission(Base):
    __tablename__ = "missions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mission_id = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    bbox = Column(JSON, nullable=False)  # [min_lat, min_lon, max_lat, max_lon]
    road_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    meta = Column(JSON, default=dict)


class Detection(Base):
    __tablename__ = "detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detection_id = Column(String(255), nullable=False, index=True)
    mission_id = Column(String(64), ForeignKey("missions.mission_id"), nullable=False, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    confidence = Column(Float, default=0.0)
    s_score = Column(Float, default=0.0)
    speed_kmh = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)
    heading_desc = Column(String(16), nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    image_url = Column(String(512), nullable=True)
    feature_signature = Column(JSON, nullable=True)
    box_shape = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_detections_location", "lat", "lon"),
        Index("ix_detections_time_location", "timestamp", "lat", "lon"),
    )


class DataFeed(Base):
    __tablename__ = "data_feeds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(64), nullable=False, index=True)  # e.g., 'opensky', 'usgs_earthquake'
    source_url = Column(String(1024), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    severity = Column(String(16), default="low")  # low, medium, high, critical
    confidence = Column(Float, default=1.0)
    raw_data = Column(JSON, default=dict)
    timestamp = Column(DateTime, nullable=False, index=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_feeds_source_time", "source", "timestamp"),
    )


class Correlation(Base):
    __tablename__ = "correlations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_a_id = Column(UUID(as_uuid=True), ForeignKey("data_feeds.id"), nullable=False)
    event_b_id = Column(UUID(as_uuid=True), ForeignKey("data_feeds.id"), nullable=False)
    relation_type = Column(String(32), nullable=False)  # spatial, temporal, semantic, causal
    confidence = Column(Float, default=0.0)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id = Column(String(64), unique=True, nullable=False, index=True)
    severity = Column(String(16), nullable=False, index=True)
    confidence = Column(Float, default=0.0)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    assumptions = Column(JSON, default=list)
    predictions = Column(JSON, default=list)
    correlated_event_ids = Column(JSON, default=list)
    recommended_action = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    dismissed = Column(Integer, default=0)  # 0 = active, 1 = dismissed
    created_at = Column(DateTime, default=datetime.utcnow)
