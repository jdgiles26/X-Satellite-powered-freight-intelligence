"""
ARGUS Ingestion Framework — Base Worker & Standard Event Model
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx

logger = logging.getLogger("ARGUS.INGESTION")


@dataclass
class StandardEvent:
    """Unified event schema for all ingested data feeds."""
    source: str
    event_type: str
    timestamp: datetime
    lat: Optional[float] = None
    lon: Optional[float] = None
    severity: str = "low"  # low, medium, high, critical
    confidence: float = 1.0
    title: str = ""
    description: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    tags: List[str] = field(default_factory=list)


class FeedWorker(ABC):
    """
    Abstract base class for all data feed workers.
    Implement fetch() + optionally normalize() for each source.
    """

    def __init__(self, interval: int = 60, http_timeout: int = 30):
        self.interval = interval
        self.http_timeout = http_timeout
        self.client = httpx.AsyncClient(timeout=http_timeout, follow_redirects=True)
        self.running = False

    @abstractmethod
    async def fetch(self) -> List[StandardEvent]:
        """Fetch raw events from the source. Must be implemented."""
        pass

    async def normalize(self, raw: Any) -> Optional[StandardEvent]:
        """
        Convert raw source data to StandardEvent.
        Override if the source requires custom normalization.
        """
        return None

    async def ingest(self, events: List[StandardEvent]):
        """
        Persist events to the database.
        Override for custom storage (e.g., direct PostgreSQL, Redis stream, etc.).
        """
        from argus.database import AsyncSessionLocal
        from argus.models import DataFeed
        from sqlalchemy.dialects.postgresql import insert

        if not events:
            return

        async with AsyncSessionLocal() as session:
            for evt in events:
                feed = DataFeed(
                    source=evt.source,
                    source_url=evt.source_url,
                    event_type=evt.event_type,
                    lat=evt.lat,
                    lon=evt.lon,
                    severity=evt.severity,
                    confidence=evt.confidence,
                    raw_data=evt.raw_data,
                    timestamp=evt.timestamp,
                )
                session.add(feed)
            await session.commit()
            logger.info(f"Ingested {len(events)} events from {events[0].source}")

    async def run_once(self):
        """Single fetch-ingest cycle."""
        try:
            events = await self.fetch()
            if events:
                await self.ingest(events)
        except Exception as e:
            logger.error(f"FeedWorker [{self.__class__.__name__}] error: {e}")

    async def run(self):
        """Continuous loop."""
        self.running = True
        logger.info(f"Starting {self.__class__.__name__} (interval={self.interval}s)")
        while self.running:
            await self.run_once()
            await asyncio.sleep(self.interval)

    async def stop(self):
        self.running = False
        await self.client.aclose()
