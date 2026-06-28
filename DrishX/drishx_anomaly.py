"""
DrishX Anomaly Detection Engine
Isolation Forest + statistical anomaly detection for freight patterns.
"""

import numpy as np
import logging
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger("ARGUS.ANOMALY")


class AnomalyEngine:
    """
    Detects anomalies in freight detection data across three dimensions:
    - Volume anomalies (unexpected detection counts per day)
    - Speed anomalies (outlier speeds for a given corridor)
    - Heading anomalies (unusual direction patterns)
    """

    SEVERITY_LEVELS = {
        "low": {"threshold": 2.0, "color": "#10b981", "label": "LOW"},
        "medium": {"threshold": 3.0, "color": "#f59e0b", "label": "MEDIUM"},
        "high": {"threshold": 4.0, "color": "#ef4444", "label": "HIGH"},
        "critical": {"threshold": float('inf'), "color": "#dc2626", "label": "CRITICAL"},
    }

    def __init__(self):
        self.volume_model = None
        self.speed_model = None
        self.baseline_stats = {}

    def _compute_severity(self, z_score: float) -> Dict:
        """Map a Z-score to a severity level."""
        abs_z = abs(z_score)
        if abs_z >= 4.0:
            return self.SEVERITY_LEVELS["critical"]
        elif abs_z >= 3.0:
            return self.SEVERITY_LEVELS["high"]
        elif abs_z >= 2.0:
            return self.SEVERITY_LEVELS["medium"]
        else:
            return self.SEVERITY_LEVELS["low"]

    def analyze_mission(self, mission: Dict) -> List[Dict]:
        """
        Analyze a single mission for anomalies.

        :param mission: mission dict from engine.history
        :return: list of anomaly records
        """
        anomalies = []
        detections = mission.get("detections", [])
        mission_id = mission.get("mission_id", "unknown")
        mission_label = mission.get("label", "Unknown")

        if not detections:
            return anomalies

        # --- 1. Volume Anomalies (per day) ---
        daily_counts = defaultdict(int)
        for d in detections:
            date_key = d.get("timestamp", "")[:10]
            if date_key:
                daily_counts[date_key] += 1

        if len(daily_counts) >= 3:
            dates = sorted(daily_counts.keys())
            counts = np.array([daily_counts[d] for d in dates], dtype=float)
            mean_c = np.mean(counts)
            std_c = np.std(counts) + 1e-6

            for date_key, count in daily_counts.items():
                z = (count - mean_c) / std_c
                if abs(z) >= 2.0:
                    sev = self._compute_severity(z)
                    anomalies.append({
                        "anomaly_id": f"vol_{mission_id}_{date_key}",
                        "mission_id": mission_id,
                        "mission_label": mission_label,
                        "type": "volume_spike",
                        "subtype": "spike" if z > 0 else "drop",
                        "date": date_key,
                        "severity": sev["label"],
                        "severity_color": sev["color"],
                        "z_score": round(float(z), 2),
                        "value": int(count),
                        "expected_range": [round(max(0, mean_c - std_c), 1), round(mean_c + std_c, 1)],
                        "description": f"{'Spike' if z > 0 else 'Drop'}: {count} detections (expected {round(mean_c, 1)}±{round(std_c, 1)})",
                        "lat": mission["bbox"][0] if "bbox" in mission else 0,
                        "lon": mission["bbox"][1] if "bbox" in mission else 0,
                    })

        # --- 2. Speed Anomalies ---
        speeds = [d.get("speed_kmh", 0) for d in detections if d.get("speed_kmh", 0) > 0]
        if len(speeds) >= 5:
            speeds_arr = np.array(speeds, dtype=float)
            mean_s = np.mean(speeds_arr)
            std_s = np.std(speeds_arr) + 1e-6

            for d in detections:
                s = d.get("speed_kmh", 0)
                if s <= 0:
                    continue
                z = (s - mean_s) / std_s
                if abs(z) >= 2.5:
                    sev = self._compute_severity(z)
                    anomalies.append({
                        "anomaly_id": f"spd_{mission_id}_{d.get('id', 'unk')}",
                        "mission_id": mission_id,
                        "mission_label": mission_label,
                        "type": "speed_outlier",
                        "subtype": "high_speed" if z > 0 else "low_speed",
                        "date": d.get("timestamp", "")[:10],
                        "severity": sev["label"],
                        "severity_color": sev["color"],
                        "z_score": round(float(z), 2),
                        "value": round(s, 1),
                        "expected_range": [round(max(0, mean_s - std_s), 1), round(mean_s + std_s, 1)],
                        "description": f"{'Unusually high' if z > 0 else 'Unusually low'} speed: {round(s, 1)} km/h (expected {round(mean_s, 1)}±{round(std_s, 1)})",
                        "lat": d.get("lat", 0),
                        "lon": d.get("lon", 0),
                        "detection_id": d.get("id"),
                    })

        # --- 3. Heading Anomalies (direction consistency) ---
        headings = [d.get("heading", None) for d in detections if d.get("heading") is not None]
        if len(headings) >= 5:
            # Compute circular mean and std
            h_rad = np.radians(headings)
            sin_h = np.mean(np.sin(h_rad))
            cos_h = np.mean(np.cos(h_rad))
            mean_heading = np.degrees(np.arctan2(sin_h, cos_h)) % 360
            r = np.sqrt(sin_h**2 + cos_h**2)
            circ_std = np.degrees(np.sqrt(-2 * np.log(max(r, 1e-9))))

            # If corridor has a dominant direction, flag outliers
            if circ_std < 60:  # Only flag if corridor has a clear direction
                for d in detections:
                    h = d.get("heading")
                    if h is None:
                        continue
                    diff = abs((h - mean_heading + 180) % 360 - 180)
                    if diff > 90:
                        anomalies.append({
                            "anomaly_id": f"hdg_{mission_id}_{d.get('id', 'unk')}",
                            "mission_id": mission_id,
                            "mission_label": mission_label,
                            "type": "heading_anomaly",
                            "subtype": "wrong_direction",
                            "date": d.get("timestamp", "")[:10],
                            "severity": "MEDIUM",
                            "severity_color": "#f59e0b",
                            "z_score": None,
                            "value": round(h, 1),
                            "expected_range": [round(mean_heading - 30, 1), round(mean_heading + 30, 1)],
                            "description": f"Heading {round(h, 1)}° deviates {round(diff, 1)}° from corridor dominant {round(mean_heading, 1)}°",
                            "lat": d.get("lat", 0),
                            "lon": d.get("lon", 0),
                            "detection_id": d.get("id"),
                        })

        # Sort by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        anomalies.sort(key=lambda x: severity_order.get(x["severity"], 99))
        return anomalies

    def analyze_all(self, history: List[Dict]) -> List[Dict]:
        """Analyze entire history for anomalies."""
        all_anomalies = []
        for mission in history:
            all_anomalies.extend(self.analyze_mission(mission))
        return all_anomalies

    def get_summary(self, history: List[Dict]) -> Dict:
        """Generate dashboard-level anomaly summary."""
        anomalies = self.analyze_all(history)
        by_severity = defaultdict(int)
        by_type = defaultdict(int)
        for a in anomalies:
            by_severity[a["severity"]] += 1
            by_type[a["type"]] += 1

        return {
            "total_anomalies": len(anomalies),
            "by_severity": dict(by_severity),
            "by_type": dict(by_type),
            "critical_count": by_severity.get("CRITICAL", 0),
            "high_count": by_severity.get("HIGH", 0),
            "latest_anomaly": anomalies[0] if anomalies else None,
        }
