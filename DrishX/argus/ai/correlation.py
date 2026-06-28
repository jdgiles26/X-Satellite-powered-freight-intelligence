"""
ARGUS AI — Spatial / Temporal Correlation Engine
"""

import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from argus.ai.llm import OllamaClient
from argus.database import AsyncSessionLocal
from argus.models import Alert, Correlation, DataFeed

from sqlalchemy import select, and_

logger = logging.getLogger("ARGUS.AI.CORRELATION")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometres."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _find_spatial_groups(
    events: List[DataFeed],
    radius_km: float = 50.0,
) -> List[List[DataFeed]]:
    """Group events that are within radius_km of each other (DBSCAN-like)."""
    if not events:
        return []
    visited = set()
    groups: List[List[DataFeed]] = []

    for i, evt in enumerate(events):
        if i in visited or evt.lat is None or evt.lon is None:
            continue
        cluster = [evt]
        visited.add(i)
        queue = [i]
        while queue:
            current_idx = queue.pop(0)
            current = events[current_idx]
            for j, other in enumerate(events):
                if j in visited or other.lat is None or other.lon is None:
                    continue
                dist = _haversine_km(current.lat, current.lon, other.lat, other.lon)
                if dist <= radius_km:
                    visited.add(j)
                    cluster.append(other)
                    queue.append(j)
        if len(cluster) > 1:
            groups.append(cluster)
    return groups


def _find_temporal_groups(
    events: List[DataFeed],
    window_hours: float = 6.0,
) -> List[List[DataFeed]]:
    """Group events that occur within window_hours of each other."""
    if not events:
        return []
    sorted_events = sorted(events, key=lambda e: e.timestamp or datetime.min)
    groups: List[List[DataFeed]] = []
    current: List[DataFeed] = [sorted_events[0]]
    for evt in sorted_events[1:]:
        last = current[-1]
        if last.timestamp and evt.timestamp:
            delta = abs((evt.timestamp - last.timestamp).total_seconds()) / 3600.0
            if delta <= window_hours:
                current.append(evt)
            else:
                if len(current) > 1:
                    groups.append(current)
                current = [evt]
        else:
            current.append(evt)
    if len(current) > 1:
        groups.append(current)
    return groups


def _build_event_summary(events: List[DataFeed]) -> str:
    """Build a concise text summary of correlated events for the LLM."""
    lines = []
    for evt in events:
        ts = evt.timestamp.isoformat() if evt.timestamp else "unknown"
        loc = f"lat={evt.lat:.4f}, lon={evt.lon:.4f}" if evt.lat is not None and evt.lon is not None else "location unknown"
        lines.append(f"- [{evt.source}] {evt.event_type} | {evt.severity} | {ts} | {loc}")
    return "\n".join(lines)


class CorrelationEngine:
    """
    Detects spatial and temporal correlations across DataFeed events
    and generates AI-driven Alerts via Ollama.
    """

    def __init__(self, ollama: Optional[OllamaClient] = None):
        self.ollama = ollama or OllamaClient()

    async def find_spatial_correlations(
        self,
        events: List[DataFeed],
        radius_km: float = 50.0,
    ) -> List[List[DataFeed]]:
        """Async wrapper for spatial grouping (runs in thread pool)."""
        return await asyncio.to_thread(_find_spatial_groups, events, radius_km)

    async def find_temporal_correlations(
        self,
        events: List[DataFeed],
        window_hours: float = 6.0,
    ) -> List[List[DataFeed]]:
        """Async wrapper for temporal grouping (runs in thread pool)."""
        return await asyncio.to_thread(_find_temporal_groups, events, window_hours)

    async def generate_alert(
        self,
        correlated_events: List[DataFeed],
    ) -> Dict[str, Any]:
        """
        Use Ollama to generate a natural-language alert with severity,
        assumptions, and predictions.
        """
        if not correlated_events:
            return {
                "alert_id": f"alt_{uuid.uuid4().hex[:8]}",
                "severity": "low",
                "confidence": 0.0,
                "title": "Empty correlation",
                "description": "No events provided for alert generation.",
                "assumptions": [],
                "predictions": [],
                "recommended_action": "None",
                "lat": None,
                "lon": None,
            }

        summary = _build_event_summary(correlated_events)
        prompt = (
            "You are ARGUS, a tactical freight-intelligence analyst. "
            "Analyze the following correlated events and produce a structured alert.\n\n"
            "Correlated Events:\n"
            f"{summary}\n\n"
            "Respond ONLY with a valid JSON object containing these exact keys:\n"
            "  severity: one of [low, medium, high, critical]\n"
            "  title: a concise alert title (max 120 chars)\n"
            "  description: a detailed natural-language description\n"
            "  assumptions: list of strings (what you assume to be true)\n"
            "  predictions: list of strings (what may happen next)\n"
            "  recommended_action: a single actionable recommendation string\n"
            "  confidence: a float 0.0–1.0 representing your certainty\n"
            "Do not wrap the JSON in markdown code blocks."
        )

        try:
            result = await self.ollama.generate(prompt=prompt)
            raw = result.get("response", "{}").strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(f"Ollama returned non-JSON alert: {exc}. Raw: {raw[:500]}")
            parsed = {
                "severity": "medium",
                "title": "Correlation Detected (Parse Error)",
                "description": raw[:512],
                "assumptions": [],
                "predictions": [],
                "recommended_action": "Review correlated events manually.",
                "confidence": 0.5,
            }
        except Exception as exc:
            logger.error(f"Alert generation failed: {exc}")
            parsed = {
                "severity": "medium",
                "title": "Correlation Detected (Generation Error)",
                "description": f"Error during LLM generation: {exc}",
                "assumptions": [],
                "predictions": [],
                "recommended_action": "Review correlated events manually.",
                "confidence": 0.3,
            }

        # Compute centroid
        lats = [e.lat for e in correlated_events if e.lat is not None]
        lons = [e.lon for e in correlated_events if e.lon is not None]
        centroid_lat = sum(lats) / len(lats) if lats else None
        centroid_lon = sum(lons) / len(lons) if lons else None

        return {
            "alert_id": f"alt_{uuid.uuid4().hex[:8]}",
            "severity": parsed.get("severity", "medium").lower(),
            "confidence": float(parsed.get("confidence", 0.5)),
            "title": parsed.get("title", "Correlation Alert"),
            "description": parsed.get("description", ""),
            "assumptions": parsed.get("assumptions", []),
            "predictions": parsed.get("predictions", []),
            "recommended_action": parsed.get("recommended_action", ""),
            "lat": centroid_lat,
            "lon": centroid_lon,
        }

    async def run_analysis(
        self,
        lookback_hours: float = 24.0,
        radius_km: float = 50.0,
        window_hours: float = 6.0,
    ) -> Dict[str, Any]:
        """
        Fetch recent DataFeed events, run spatial+temporal correlation,
        generate alerts, persist Correlations and Alerts to the DB.
        """
        since = datetime.utcnow() - timedelta(hours=lookback_hours)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DataFeed)
                .where(DataFeed.timestamp >= since)
                .order_by(DataFeed.timestamp.desc())
            )
            events = result.scalars().all()

        if not events:
            logger.info("Correlation analysis: no recent events.")
            return {"status": "no_data", "alerts_created": 0, "correlations_created": 0}

        logger.info(f"Correlation analysis: {len(events)} events in lookback window.")

        # Run correlations in parallel
        spatial_task = asyncio.create_task(
            self.find_spatial_correlations(list(events), radius_km)
        )
        temporal_task = asyncio.create_task(
            self.find_temporal_correlations(list(events), window_hours)
        )
        spatial_groups, temporal_groups = await asyncio.gather(spatial_task, temporal_task)

        # Deduplicate combined groups by event ID set
        seen_ids: set = set()
        combined_groups: List[List[DataFeed]] = []
        for group in spatial_groups + temporal_groups:
            key = tuple(sorted(str(e.id) for e in group))
            if key not in seen_ids:
                seen_ids.add(key)
                combined_groups.append(group)

        alerts_created = 0
        correlations_created = 0

        async with AsyncSessionLocal() as session:
            for group in combined_groups:
                if len(group) < 2:
                    continue

                # Persist correlations (pairwise)
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        corr = Correlation(
                            event_a_id=group[i].id,
                            event_b_id=group[j].id,
                            relation_type="spatial" if group in spatial_groups else "temporal",
                            confidence=0.7,
                            explanation=f"Auto-detected within {radius_km} km / {window_hours} h",
                        )
                        session.add(corr)
                        correlations_created += 1

                # Generate and persist alert
                try:
                    alert_data = await self.generate_alert(group)
                except Exception as exc:
                    logger.error(f"Alert generation failed for group: {exc}")
                    continue

                alert = Alert(
                    alert_id=alert_data["alert_id"],
                    severity=alert_data["severity"],
                    confidence=alert_data["confidence"],
                    title=alert_data["title"],
                    description=alert_data["description"],
                    assumptions=alert_data["assumptions"],
                    predictions=alert_data["predictions"],
                    correlated_event_ids=[str(e.id) for e in group],
                    recommended_action=alert_data["recommended_action"],
                    lat=alert_data["lat"],
                    lon=alert_data["lon"],
                    dismissed=0,
                )
                session.add(alert)
                alerts_created += 1

            await session.commit()

        logger.info(
            f"Correlation analysis complete: {alerts_created} alerts, {correlations_created} correlations."
        )
        return {
            "status": "success",
            "alerts_created": alerts_created,
            "correlations_created": correlations_created,
            "spatial_groups": len(spatial_groups),
            "temporal_groups": len(temporal_groups),
        }
