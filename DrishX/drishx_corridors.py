"""
DrishX Corridor Clustering Engine
DBSCAN-based spatial-angular clustering to discover persistent freight corridors.
"""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger("ARGUS.CORRIDORS")


class CorridorEngine:
    """
    Clusters truck detections across missions and time to identify
    persistent freight corridors using DBSCAN with heading constraints.
    """

    def __init__(self, eps_meters: float = 50.0, min_samples: int = 3,
                 heading_tolerance: float = 30.0):
        """
        :param eps_meters: DBSCAN epsilon in meters (~50m = highway lane context)
        :param min_samples: minimum detections to form a corridor cluster
        :param heading_tolerance: max heading difference in degrees for clustering
        """
        self.eps_meters = eps_meters
        self.min_samples = min_samples
        self.heading_tolerance = heading_tolerance

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance in meters."""
        R = 6371000  # Earth radius in meters
        phi1, phi2 = np.radians(lat1), np.radians(lat2)
        dphi = np.radians(lat2 - lat1)
        dlambda = np.radians(lon2 - lon1)
        a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
        return 2 * R * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    def _heading_difference(self, h1: float, h2: float) -> float:
        """Compute smallest angular difference between two headings."""
        diff = abs((h1 - h2 + 180) % 360 - 180)
        return diff

    def _custom_distance_matrix(self, detections: List[Dict]) -> np.ndarray:
        """
        Build a custom distance matrix combining spatial and heading distance.
        Spatial distance in meters, heading distance scaled to comparable range.
        """
        n = len(detections)
        coords = np.array([[d["lat"], d["lon"]] for d in detections])
        headings = np.array([d.get("heading", 0) for d in detections])

        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                spatial = self._haversine_distance(
                    coords[i][0], coords[i][1],
                    coords[j][0], coords[j][1]
                )
                heading_diff = self._heading_difference(headings[i], headings[j])
                # Scale heading diff: 30° diff adds ~30m equivalent distance
                heading_penalty = heading_diff * (self.eps_meters / self.heading_tolerance)
                combined = spatial + heading_penalty
                dist_matrix[i, j] = combined
                dist_matrix[j, i] = combined
        return dist_matrix

    def discover_corridors(self, history: List[Dict]) -> List[Dict]:
        """
        Discover freight corridors from all detection history.

        :param history: list of mission dicts from engine.history
        :return: list of corridor dicts with GeoJSON-friendly geometry
        """
        # Collect all detections
        all_dets = []
        for mission in history:
            for d in mission.get("detections", []):
                det = dict(d)
                det["_mission_id"] = mission.get("mission_id", "unknown")
                all_dets.append(det)

        if len(all_dets) < self.min_samples:
            logger.info(f"CorridorEngine: Only {len(all_dets)} detections total — need {self.min_samples}.")
            return []

        try:
            from sklearn.cluster import DBSCAN
        except ImportError:
            logger.error("CorridorEngine: sklearn not available for DBSCAN.")
            return []

        dist_matrix = self._custom_distance_matrix(all_dets)

        # Run DBSCAN with precomputed distances
        # eps is scaled: we use combined distance, so eps = eps_meters * 2 as heuristic
        dbscan = DBSCAN(
            eps=self.eps_meters * 2,
            min_samples=self.min_samples,
            metric="precomputed",
        )
        labels = dbscan.fit_predict(dist_matrix)

        # Build corridor objects from clusters
        corridors = []
        unique_labels = set(labels)
        for label in unique_labels:
            if label == -1:
                continue  # Noise

            cluster_indices = np.where(labels == label)[0]
            cluster_dets = [all_dets[i] for i in cluster_indices]

            if len(cluster_dets) < self.min_samples:
                continue

            # Compute corridor centroid and bounding geometry
            lats = [d["lat"] for d in cluster_dets]
            lons = [d["lon"] for d in cluster_dets]
            headings = [d.get("heading", 0) for d in cluster_dets if d.get("heading") is not None]
            speeds = [d.get("speed_kmh", 0) for d in cluster_dets if d.get("speed_kmh", 0) > 0]
            timestamps = [d.get("timestamp", "") for d in cluster_dets]

            centroid_lat = float(np.mean(lats))
            centroid_lon = float(np.mean(lons))

            # Dominant heading (circular mean)
            if headings:
                h_rad = np.radians(headings)
                sin_h = np.mean(np.sin(h_rad))
                cos_h = np.mean(np.cos(h_rad))
                dominant_heading = float(np.degrees(np.arctan2(sin_h, cos_h)) % 360)
                heading_std = float(np.degrees(np.sqrt(-2 * np.log(min(1, np.sqrt(sin_h**2 + cos_h**2) + 1e-9)))))
            else:
                dominant_heading = 0.0
                heading_std = 0.0

            # Temporal span
            valid_ts = [t for t in timestamps if t]
            temporal_span = None
            if valid_ts:
                from datetime import datetime
                try:
                    dates = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in valid_ts]
                    temporal_span = (max(dates) - min(dates)).days
                except Exception:
                    temporal_span = None

            # Build line geometry (simplified: centroid ± dominant heading at extent)
            extent_m = max(
                self._haversine_distance(centroid_lat, centroid_lon, max(lats), centroid_lon),
                self._haversine_distance(centroid_lat, centroid_lon, min(lats), centroid_lon),
                self._haversine_distance(centroid_lat, centroid_lon, centroid_lat, max(lons)),
                self._haversine_distance(centroid_lat, centroid_lon, centroid_lat, min(lons)),
            )

            # Create a simple line along dominant heading through centroid
            half_len_deg = (extent_m / 2) / 111320  # rough meters to degrees
            heading_rad = np.radians(dominant_heading)
            line_start = [
                centroid_lat - half_len_deg * np.cos(heading_rad),
                centroid_lon - half_len_deg * np.sin(heading_rad) / np.cos(np.radians(centroid_lat)),
            ]
            line_end = [
                centroid_lat + half_len_deg * np.cos(heading_rad),
                centroid_lon + half_len_deg * np.sin(heading_rad) / np.cos(np.radians(centroid_lat)),
            ]

            corridor = {
                "corridor_id": f"corridor_{label}",
                "detection_count": len(cluster_dets),
                "centroid": {"lat": round(centroid_lat, 6), "lon": round(centroid_lon, 6)},
                "dominant_heading": round(dominant_heading, 1),
                "heading_std": round(heading_std, 1),
                "avg_speed_kmh": round(float(np.mean(speeds)), 1) if speeds else 0.0,
                "speed_std_kmh": round(float(np.std(speeds)), 1) if speeds else 0.0,
                "temporal_span_days": temporal_span,
                "density_score": round(len(cluster_dets) / (extent_m / 1000 + 0.001), 2),  # detections per km
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [round(line_start[1], 6), round(line_start[0], 6)],
                        [round(line_end[1], 6), round(line_end[0], 6)],
                    ]
                },
                "bbox": [
                    round(min(lons), 6),
                    round(min(lats), 6),
                    round(max(lons), 6),
                    round(max(lats), 6),
                ],
                "missions_involved": list(set(d["_mission_id"] for d in cluster_dets)),
            }
            corridors.append(corridor)

        # Sort by density score descending
        corridors.sort(key=lambda c: c["density_score"], reverse=True)
        return corridors

    def get_corridor_timeline(self, corridor_id: str, history: List[Dict]) -> Dict:
        """
        Get a temporal profile for a specific corridor.
        Currently returns daily aggregated stats for detections near the corridor centroid.
        """
        # Find the corridor first
        corridors = self.discover_corridors(history)
        corridor = next((c for c in corridors if c["corridor_id"] == corridor_id), None)
        if not corridor:
            return {"error": "Corridor not found"}

        centroid = corridor["centroid"]
        daily = defaultdict(lambda: {"count": 0, "speeds": [], "headings": []})

        for mission in history:
            for d in mission.get("detections", []):
                dist = self._haversine_distance(
                    centroid["lat"], centroid["lon"],
                    d.get("lat", 0), d.get("lon", 0)
                )
                if dist <= self.eps_meters * 2:
                    date_key = d.get("timestamp", "")[:10] or "unknown"
                    daily[date_key]["count"] += 1
                    if d.get("speed_kmh", 0) > 0:
                        daily[date_key]["speeds"].append(d["speed_kmh"])
                    if d.get("heading") is not None:
                        daily[date_key]["headings"].append(d["heading"])

        timeline = []
        for date_key in sorted(daily.keys()):
            entry = daily[date_key]
            timeline.append({
                "date": date_key,
                "count": entry["count"],
                "avg_speed": round(float(np.mean(entry["speeds"])), 1) if entry["speeds"] else None,
                "avg_heading": round(float(np.mean(entry["headings"])), 1) if entry["headings"] else None,
            })

        return {
            "corridor_id": corridor_id,
            "timeline": timeline,
            "peak_day": max(timeline, key=lambda x: x["count"])["date"] if timeline else None,
        }
