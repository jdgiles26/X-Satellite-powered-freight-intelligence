"""
DrishX XAI Explainability Engine
SHAP-based spectral explainability for S2TruckDetect classifications.
"""

import numpy as np
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("ARGUS.XAI")


class XAIEngine:
    """
    Explainability engine for Sentinel-2 truck detections.
    Uses SHAP TreeExplainer for exact feature attribution on the Random Forest.
    """

    FEATURE_NAMES = [
        "variance_RGB",
        "norm_ratio_red_blue",
        "norm_ratio_green_blue",
        "centered_red",
        "centered_green",
        "centered_blue",
        "centered_nir",
    ]

    FEATURE_DESCRIPTIONS = {
        "variance_RGB": "Spectral variance across visible bands — trucks show high variance due to sensor displacement.",
        "norm_ratio_red_blue": "Red/Blue normalized ratio — captures directional spectral shift.",
        "norm_ratio_green_blue": "Green/Blue normalized ratio — secondary displacement indicator.",
        "centered_red": "Mean-centered red reflectance — deviation from local background.",
        "centered_green": "Mean-centered green reflectance — deviation from local background.",
        "centered_blue": "Mean-centered blue reflectance — deviation from local background.",
        "centered_nir": "Mean-centered NIR reflectance — vegetation vs. vehicle contrast.",
    }

    def __init__(self, rf_model):
        self.rf_model = rf_model
        self.explainer = None
        self._init_explainer()

    def _init_explainer(self):
        if self.rf_model is None:
            logger.warning("XAIEngine: No RF model provided — explanations will be approximate.")
            return
        try:
            import shap
            self.explainer = shap.TreeExplainer(self.rf_model)
            logger.info("XAIEngine: SHAP TreeExplainer initialized.")
        except Exception as e:
            logger.error(f"XAIEngine: Failed to initialize SHAP explainer: {e}")

    def explain_detection(self, feature_signature: Optional[List[float]] = None,
                          feature_stack: Optional[np.ndarray] = None,
                          road_mask: Optional[np.ndarray] = None,
                          detection_box: Optional[Dict] = None) -> Dict:
        """
        Generate SHAP explanation for a detection.

        Uses pre-computed feature_signature if available (lightweight),
        otherwise falls back to full feature_stack computation.

        :param feature_signature: pre-computed mean feature vector (7,)
        :param feature_stack: (7, H, W) feature array (fallback)
        :param road_mask: (H, W) binary road mask (fallback)
        :param detection_box: optional dict with keys ymin, ymax, xmin, xmax defining the detection region (fallback)
        :return: explanation dict with feature contributions and confidence breakdown
        """
        # Fast path: use pre-computed feature signature
        if feature_signature is not None and len(feature_signature) == 7:
            return self._explain_from_signature(feature_signature)

        # Fallback: compute from full feature stack
        if feature_stack is None:
            return self._fallback_explanation_empty()

        if self.explainer is None or self.rf_model is None:
            return self._fallback_explanation(feature_stack, road_mask, detection_box)

        H, W = feature_stack.shape[1], feature_stack.shape[2]

        if detection_box:
            ymin, ymax = detection_box.get("ymin", 0), detection_box.get("ymax", H)
            xmin, xmax = detection_box.get("xmin", 0), detection_box.get("xmax", W)
        else:
            ymin, ymax, xmin, xmax = 0, H, 0, W

        roi_features = feature_stack[:, ymin:ymax, xmin:xmax]
        roi_road = road_mask[ymin:ymax, xmin:xmax] if road_mask is not None else np.ones((ymax-ymin, xmax-xmin))

        n_channels = roi_features.shape[0]
        roi_flat = roi_features.reshape(n_channels, -1).T
        road_flat = roi_road.flatten()

        valid = road_flat.astype(bool) & np.all(np.isfinite(roi_flat), axis=1)
        if not np.any(valid):
            return self._fallback_explanation(feature_stack, road_mask, detection_box)

        valid_pixels = roi_flat[valid]

        try:
            shap_values = self.explainer.shap_values(valid_pixels)

            if isinstance(shap_values, list):
                truck_shap = np.mean([np.abs(shap_values[c]) for c in range(1, min(4, len(shap_values)))], axis=0)
                truck_expected = np.mean([self.explainer.expected_value[c] for c in range(1, min(4, len(shap_values)))])
            else:
                truck_shap = np.abs(shap_values)
                truck_expected = self.explainer.expected_value

            mean_shap = np.mean(truck_shap, axis=0).tolist()
            ranked = sorted(zip(self.FEATURE_NAMES, mean_shap), key=lambda x: x[1], reverse=True)
            total = sum(v for _, v in ranked) + 1e-9
            contributions = [
                {
                    "feature": name,
                    "description": self.FEATURE_DESCRIPTIONS.get(name, ""),
                    "importance": round(val, 6),
                    "percentage": round(val / total * 100, 1),
                    "rank": i + 1,
                }
                for i, (name, val) in enumerate(ranked)
            ]
            signature = np.mean(valid_pixels, axis=0).tolist()

            return {
                "method": "shap_tree_explainer",
                "expected_value": float(truck_expected) if not isinstance(truck_expected, (list, np.ndarray)) else float(np.mean(truck_expected)),
                "pixel_count": int(np.sum(valid)),
                "contributions": contributions,
                "signature": {name: round(v, 4) for name, v in zip(self.FEATURE_NAMES, signature)},
                "top_driver": contributions[0]["feature"] if contributions else None,
            }

        except Exception as e:
            logger.error(f"XAIEngine: SHAP computation failed: {e}")
            return self._fallback_explanation(feature_stack, road_mask, detection_box)

    def _explain_from_signature(self, feature_signature: List[float]) -> Dict:
        """Generate explanation from a pre-computed 7-element feature signature."""
        arr = np.array(feature_signature, dtype=float)
        # Use absolute values as proxy for feature importance (heuristic)
        abs_vals = np.abs(arr)
        total = np.sum(abs_vals) + 1e-9

        contributions = [
            {
                "feature": name,
                "description": self.FEATURE_DESCRIPTIONS.get(name, ""),
                "importance": round(float(val), 6),
                "percentage": round(float(val / total * 100), 1),
                "rank": i + 1,
            }
            for i, (name, val) in enumerate(
                sorted(zip(self.FEATURE_NAMES, abs_vals), key=lambda x: x[1], reverse=True)
            )
        ]

        if self.explainer is not None and self.rf_model is not None:
            try:
                shap_values = self.explainer.shap_values(arr.reshape(1, -1))
                if isinstance(shap_values, list):
                    truck_shap = np.mean([np.abs(shap_values[c]) for c in range(1, min(4, len(shap_values)))], axis=0)[0]
                    truck_expected = np.mean([self.explainer.expected_value[c] for c in range(1, min(4, len(shap_values)))])
                else:
                    truck_shap = np.abs(shap_values)[0]
                    truck_expected = self.explainer.expected_value

                shap_total = np.sum(truck_shap) + 1e-9
                contributions = [
                    {
                        "feature": name,
                        "description": self.FEATURE_DESCRIPTIONS.get(name, ""),
                        "importance": round(float(val), 6),
                        "percentage": round(float(val / shap_total * 100), 1),
                        "rank": i + 1,
                    }
                    for i, (name, val) in enumerate(
                        sorted(zip(self.FEATURE_NAMES, truck_shap), key=lambda x: x[1], reverse=True)
                    )
                ]
                method = "shap_tree_explainer_signature"
                expected_val = float(truck_expected) if not isinstance(truck_expected, (list, np.ndarray)) else float(np.mean(truck_expected))
            except Exception as e:
                logger.warning(f"SHAP signature explanation failed: {e}")
                method = "heuristic_signature"
                expected_val = 0.0
        else:
            method = "heuristic_signature"
            expected_val = 0.0

        return {
            "method": method,
            "expected_value": expected_val,
            "pixel_count": 1,
            "contributions": contributions,
            "signature": {name: round(v, 4) for name, v in zip(self.FEATURE_NAMES, feature_signature)},
            "top_driver": contributions[0]["feature"] if contributions else None,
        }

    def _fallback_explanation_empty(self) -> Dict:
        """Empty fallback when no data is available."""
        return {
            "method": "unavailable",
            "contributions": [],
            "signature": {},
            "top_driver": None,
        }

    def _fallback_explanation(self, feature_stack: np.ndarray, road_mask: np.ndarray,
                              detection_box: Optional[Dict] = None) -> Dict:
        """Heuristic fallback when SHAP is unavailable."""
        H, W = feature_stack.shape[1], feature_stack.shape[2]
        if detection_box:
            ymin, ymax = detection_box.get("ymin", 0), detection_box.get("ymax", H)
            xmin, xmax = detection_box.get("xmin", 0), detection_box.get("xmax", W)
        else:
            ymin, ymax, xmin, xmax = 0, H, 0, W

        roi = feature_stack[:, ymin:ymax, xmin:xmax]
        roi_road = road_mask[ymin:ymax, xmin:xmax]

        n_channels = roi.shape[0]
        roi_flat = roi.reshape(n_channels, -1).T
        road_flat = roi_road.flatten()
        valid = road_flat.astype(bool) & np.all(np.isfinite(roi_flat), axis=1)

        if not np.any(valid):
            return {
                "method": "fallback_unavailable",
                "contributions": [],
                "signature": {},
                "top_driver": None,
            }

        valid_pixels = roi_flat[valid]
        means = np.mean(np.abs(valid_pixels), axis=0)
        total = np.sum(means) + 1e-9

        contributions = [
            {
                "feature": name,
                "description": self.FEATURE_DESCRIPTIONS.get(name, ""),
                "importance": round(float(val), 6),
                "percentage": round(float(val / total * 100), 1),
                "rank": i + 1,
            }
            for i, (name, val) in enumerate(
                sorted(zip(self.FEATURE_NAMES, means), key=lambda x: x[1], reverse=True)
            )
        ]

        signature = np.mean(valid_pixels, axis=0).tolist()

        return {
            "method": "fallback_heuristic",
            "contributions": contributions,
            "signature": {name: round(v, 4) for name, v in zip(self.FEATURE_NAMES, signature)},
            "top_driver": contributions[0]["feature"] if contributions else None,
        }
