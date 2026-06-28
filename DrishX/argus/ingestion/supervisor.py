"""
ARGUS Ingestion Supervisor

Orchestrates all feed workers concurrently and handles graceful shutdown.
"""

import asyncio
import logging
import signal
from typing import List

from argus.ingestion.base import FeedWorker
from argus.ingestion.feeds import (
    USGSEarthquakeWorker,
    NOAAAlertWorker,
    OpenSkyWorker,
    OpenWeatherWorker,
    NewsAPIWorker,
    BlueskyWorker,
)

logger = logging.getLogger("ARGUS.INGESTION.SUPERVISOR")


class IngestionSupervisor:
    """Manages the lifecycle of all ingestion workers."""

    def __init__(self):
        self.workers: List[FeedWorker] = [
            USGSEarthquakeWorker(interval=300),
            NOAAAlertWorker(interval=300),
            OpenSkyWorker(interval=60),
            OpenWeatherWorker(interval=600),
            NewsAPIWorker(interval=900),
            BlueskyWorker(interval=300),
        ]
        self._tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Start all workers concurrently and block until shutdown is requested."""
        logger.info("Starting IngestionSupervisor with %d workers", len(self.workers))

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except (NotImplementedError, ValueError):
                # Windows or event-loop limitations
                pass

        self._tasks = [asyncio.create_task(w.run()) for w in self.workers]
        await self._shutdown_event.wait()
        await self.shutdown()

    def _request_shutdown(self):
        logger.info("Shutdown signal received — requesting supervisor stop")
        self._shutdown_event.set()

    async def shutdown(self):
        """Signal all workers to stop and await their tasks."""
        logger.info("Shutting down IngestionSupervisor")
        for worker in self.workers:
            await worker.stop()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("IngestionSupervisor shutdown complete")
