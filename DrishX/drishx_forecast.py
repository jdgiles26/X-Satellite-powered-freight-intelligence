"""
DrishX Temporal Forecasting Engine
Prophet-based freight volume forecasting from detection history.
"""

import numpy as np
import logging
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger("ARGUS.FORECAST")


class ForecastEngine:
    """
    Forecast future freight detection volumes using Facebook Prophet.
    Falls back to simple exponential smoothing if Prophet is unavailable.
    """

    def __init__(self):
        self.prophet_available = self._check_prophet()

    def _check_prophet(self) -> bool:
        try:
            from prophet import Prophet
            return True
        except ImportError:
            logger.warning("Prophet not available — forecasting will use exponential smoothing fallback.")
            return False

    def _aggregate_daily(self, detections: List[Dict]) -> Dict[str, int]:
        """Aggregate detections into daily counts."""
        daily = defaultdict(int)
        for d in detections:
            ts = d.get("timestamp", "")
            if len(ts) >= 10:
                daily[ts[:10]] += 1
        return dict(daily)

    def _exponential_smoothing_forecast(self, dates: List[str], values: List[int],
                                        horizon_days: int = 14) -> Dict:
        """Simple exponential smoothing fallback."""
        arr = np.array(values, dtype=float)
        alpha = 0.3

        # Fit smoothing
        smoothed = np.zeros_like(arr)
        smoothed[0] = arr[0]
        for i in range(1, len(arr)):
            smoothed[i] = alpha * arr[i] + (1 - alpha) * smoothed[i-1]

        # Forecast
        last_val = smoothed[-1]
        last_date = datetime.strptime(dates[-1], "%Y-%m-%d")
        forecast_dates = []
        forecast_values = []
        forecast_lower = []
        forecast_upper = []

        for i in range(1, horizon_days + 1):
            fc_date = last_date + timedelta(days=i)
            fc_val = last_val  # flat forecast with smoothing
            std = np.std(arr[-min(7, len(arr)):]) + 1e-6
            forecast_dates.append(fc_date.strftime("%Y-%m-%d"))
            forecast_values.append(round(max(0, fc_val), 1))
            forecast_lower.append(round(max(0, fc_val - 1.96 * std), 1))
            forecast_upper.append(round(max(0, fc_val + 1.96 * std), 1))

        return {
            "method": "exponential_smoothing",
            "dates": forecast_dates,
            "forecast": forecast_values,
            "lower_bound": forecast_lower,
            "upper_bound": forecast_upper,
            "historical_dates": dates,
            "historical_values": [int(v) for v in values],
        }

    def forecast_mission(self, mission: Dict, horizon_days: int = 14) -> Dict:
        """
        Generate a freight volume forecast for a mission.

        :param mission: mission dict from engine.history
        :param horizon_days: number of days to forecast ahead
        :return: forecast dict with dates, predicted values, and confidence intervals
        """
        detections = mission.get("detections", [])
        mission_id = mission.get("mission_id", "unknown")
        mission_label = mission.get("label", "Unknown")

        if not detections:
            return {
                "mission_id": mission_id,
                "mission_label": mission_label,
                "error": "No detection data available for forecasting.",
                "method": "none",
            }

        daily = self._aggregate_daily(detections)
        if len(daily) < 3:
            return {
                "mission_id": mission_id,
                "mission_label": mission_label,
                "error": f"Insufficient data points ({len(daily)} days). Need at least 3.",
                "method": "none",
            }

        dates = sorted(daily.keys())
        values = [daily[d] for d in dates]

        if self.prophet_available:
            try:
                from prophet import Prophet

                df = []
                for d, v in zip(dates, values):
                    df.append({"ds": d, "y": v})

                # Prophet requires a DataFrame-like structure
                import pandas as pd
                df = pd.DataFrame(df)

                m = Prophet(
                    daily_seasonality=False,
                    yearly_seasonality=len(dates) >= 30,
                    weekly_seasonality=len(dates) >= 7,
                    interval_width=0.95,
                )
                m.fit(df)

                future = m.make_future_dataframe(periods=horizon_days)
                forecast = m.predict(future)

                # Extract future predictions
                hist_len = len(dates)
                fc_dates = forecast["ds"].iloc[hist_len:].dt.strftime("%Y-%m-%d").tolist()
                fc_yhat = forecast["yhat"].iloc[hist_len:].clip(lower=0).round(1).tolist()
                fc_lower = forecast["yhat_lower"].iloc[hist_len:].clip(lower=0).round(1).tolist()
                fc_upper = forecast["yhat_upper"].iloc[hist_len:].clip(lower=0).round(1).tolist()

                return {
                    "mission_id": mission_id,
                    "mission_label": mission_label,
                    "method": "prophet",
                    "dates": fc_dates,
                    "forecast": fc_yhat,
                    "lower_bound": fc_lower,
                    "upper_bound": fc_upper,
                    "historical_dates": dates,
                    "historical_values": [int(v) for v in values],
                    "trend": "increasing" if fc_yhat and fc_yhat[-1] > values[-1] else "decreasing" if fc_yhat and fc_yhat[-1] < values[-1] else "stable",
                }

            except Exception as e:
                logger.error(f"Prophet forecasting failed: {e} — falling back to exponential smoothing.")
                return self._exponential_smoothing_forecast(dates, values, horizon_days)
        else:
            return self._exponential_smoothing_forecast(dates, values, horizon_days)

    def forecast_all(self, history: List[Dict], horizon_days: int = 14) -> List[Dict]:
        """Generate forecasts for all missions in history."""
        results = []
        for mission in history:
            fc = self.forecast_mission(mission, horizon_days)
            if "error" not in fc:
                results.append(fc)
        return results
