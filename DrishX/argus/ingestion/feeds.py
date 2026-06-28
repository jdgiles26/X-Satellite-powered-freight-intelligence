"""
ARGUS Ingestion — Concrete Feed Workers

All workers use only public, free, legal open-data APIs.
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional, Any

import httpx

from argus.ingestion.base import FeedWorker, StandardEvent

logger = logging.getLogger("ARGUS.INGESTION.FEEDS")


def _parse_iso_timestamp(value: Optional[str]) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware UTC datetime."""
    if not value:
        return datetime.now(timezone.utc)
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def _map_generic_severity(text: str) -> str:
    """Infer ARGUS severity from free-text keywords."""
    text = text.lower()
    critical = ["disaster", "catastrophe", "war", "attack", "terror", "collapse", "fatal"]
    high = ["crash", "strike", "protest", "blockade", "shutdown", "emergency"]
    medium = ["delay", "disruption", "closure", "accident", "storm", "flood", "congestion"]
    if any(k in text for k in critical):
        return "critical"
    if any(k in text for k in high):
        return "high"
    if any(k in text for k in medium):
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────────────
# 1. USGS Earthquake
# ─────────────────────────────────────────────────────────────────────────────

class USGSEarthquakeWorker(FeedWorker):
    """Ingests significant earthquakes from USGS GeoJSON feed."""

    SOURCE = "usgs_earthquake"
    URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"

    def __init__(self, interval: int = 300, http_timeout: int = 30):
        super().__init__(interval=interval, http_timeout=http_timeout)

    async def fetch(self) -> List[StandardEvent]:
        try:
            resp = await self.client.get(self.URL)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("USGS fetch failed: %s", exc)
            return []

        events: List[StandardEvent] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [None, None, None])

            ts_ms = props.get("time")
            ts = (
                datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                if ts_ms else datetime.now(timezone.utc)
            )

            mag = props.get("mag") or 0.0
            alert = props.get("alert", "")
            severity = self._map_severity(mag, alert)

            event = StandardEvent(
                source=self.SOURCE,
                event_type="earthquake",
                timestamp=ts,
                lat=coords[1],
                lon=coords[0],
                severity=severity,
                confidence=min(mag / 10.0, 1.0),
                title=f"M{mag} Earthquake — {props.get('place', 'Unknown')}",
                description=props.get("title", ""),
                raw_data=props,
                source_url=props.get("url") or self.URL,
                tags=["natural_disaster", "seismic"]
                + (["tsunami"] if props.get("tsunami") else []),
            )
            events.append(event)
        return events

    @staticmethod
    def _map_severity(mag: float, alert: str) -> str:
        if alert == "red" or mag >= 7.0:
            return "critical"
        if alert == "orange" or mag >= 6.0:
            return "high"
        if alert == "yellow" or mag >= 5.0:
            return "medium"
        return "low"


# ─────────────────────────────────────────────────────────────────────────────
# 2. NOAA Weather Alerts
# ─────────────────────────────────────────────────────────────────────────────

class NOAAAlertWorker(FeedWorker):
    """Ingests active CAP weather alerts from the US National Weather Service."""

    SOURCE = "noaa_alert"
    URL = "https://api.weather.gov/alerts/active"

    def __init__(self, interval: int = 300, http_timeout: int = 30):
        super().__init__(interval=interval, http_timeout=http_timeout)

    async def fetch(self) -> List[StandardEvent]:
        try:
            resp = await self.client.get(self.URL)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("NOAA fetch failed: %s", exc)
            return []

        events: List[StandardEvent] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            ts = _parse_iso_timestamp(props.get("effective"))
            severity = self._map_noaa_severity(props.get("severity", "Unknown"))

            event = StandardEvent(
                source=self.SOURCE,
                event_type=props.get("event", "weather_alert").lower().replace(" ", "_"),
                timestamp=ts,
                severity=severity,
                confidence=0.9,
                title=props.get("headline", props.get("event", "Weather Alert")),
                description=props.get("description", ""),
                raw_data=props,
                source_url=props.get("id") or self.URL,
                tags=["weather", props.get("status", "actual").lower()],
            )
            events.append(event)
        return events

    @staticmethod
    def _map_noaa_severity(sev: str) -> str:
        mapping = {
            "extreme": "critical",
            "severe": "high",
            "moderate": "medium",
            "minor": "low",
        }
        return mapping.get(sev.lower(), "low")


# ─────────────────────────────────────────────────────────────────────────────
# 3. OpenSky ADS-B
# ─────────────────────────────────────────────────────────────────────────────

class OpenSkyWorker(FeedWorker):
    """Ingests global aircraft state vectors from the OpenSky Network."""

    SOURCE = "opensky"
    URL = "https://opensky-network.org/api/states/all"

    def __init__(self, interval: int = 60, http_timeout: int = 30):
        super().__init__(interval=interval, http_timeout=http_timeout)

    async def fetch(self) -> List[StandardEvent]:
        try:
            resp = await self.client.get(self.URL)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("OpenSky fetch failed: %s", exc)
            return []

        snapshot_time = data.get("time")
        states = data.get("states") or []
        events: List[StandardEvent] = []
        truncated = False

        # Guard against unbounded ingestion — OpenSky can return 5 000+ aircraft.
        MAX_STATES = 2_000
        if len(states) > MAX_STATES:
            states = states[:MAX_STATES]
            truncated = True

        for state in states:
            if not state or len(state) < 6:
                continue
            lat = state[6]
            lon = state[5]
            if lat is None or lon is None:
                continue

            time_pos = state[3]
            if time_pos:
                ts = datetime.fromtimestamp(time_pos, tz=timezone.utc)
            else:
                ts = (
                    datetime.fromtimestamp(snapshot_time, tz=timezone.utc)
                    if snapshot_time else datetime.now(timezone.utc)
                )

            callsign = (state[1] or "").strip()
            origin = state[2] or "Unknown"
            on_ground = state[8]
            velocity = state[9]

            event = StandardEvent(
                source=self.SOURCE,
                event_type="aircraft_position",
                timestamp=ts,
                lat=float(lat),
                lon=float(lon),
                severity="low",
                confidence=0.8,
                title=f"Aircraft {callsign or state[0]} ({origin})",
                description=(
                    f"Velocity: {velocity} m/s, On ground: {on_ground}, "
                    f"Baro altitude: {state[7]} m"
                ),
                raw_data={"state_vector": state},
                source_url=self.URL,
                tags=["ads-b", "aviation", "freight" if not on_ground else "ground"],
            )
            events.append(event)

        if truncated:
            logger.warning(
                "OpenSky returned >%d states; ingested first %d only", MAX_STATES, MAX_STATES
            )
        return events


# ─────────────────────────────────────────────────────────────────────────────
# 4. OpenWeather
# ─────────────────────────────────────────────────────────────────────────────

class OpenWeatherWorker(FeedWorker):
    """Ingests current weather for a configurable list of cities."""

    SOURCE = "openweather"
    DEFAULT_CITIES = [
        {"name": "Frankfurt", "lat": 50.11, "lon": 8.68},
        {"name": "Berlin", "lat": 52.52, "lon": 13.41},
        {"name": "Hamburg", "lat": 53.55, "lon": 9.99},
    ]

    def __init__(
        self,
        interval: int = 600,
        http_timeout: int = 30,
        cities: Optional[List[dict]] = None,
    ):
        super().__init__(interval=interval, http_timeout=http_timeout)
        self.cities = cities or list(self.DEFAULT_CITIES)
        self.api_key = os.getenv("OPENWEATHER_API_KEY")

    async def fetch(self) -> List[StandardEvent]:
        if not self.api_key:
            logger.warning("OpenWeatherWorker: OPENWEATHER_API_KEY not set; skipping.")
            return []

        events: List[StandardEvent] = []
        base_url = "https://api.openweathermap.org/data/2.5/weather"

        for city in self.cities:
            params = {
                "lat": city["lat"],
                "lon": city["lon"],
                "appid": self.api_key,
                "units": "metric",
            }
            try:
                resp = await self.client.get(base_url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as exc:
                logger.warning("OpenWeather fetch failed for %s: %s", city["name"], exc)
                continue

            ts_unix = data.get("dt")
            ts = (
                datetime.fromtimestamp(ts_unix, tz=timezone.utc)
                if ts_unix else datetime.now(timezone.utc)
            )

            weather = data.get("weather", [{}])[0]
            main = data.get("main", {})
            wind = data.get("wind", {})
            severity = self._map_severity(weather, wind)

            event = StandardEvent(
                source=self.SOURCE,
                event_type="weather_current",
                timestamp=ts,
                lat=data.get("coord", {}).get("lat"),
                lon=data.get("coord", {}).get("lon"),
                severity=severity,
                confidence=0.85,
                title=f"Weather in {data.get('name', city['name'])}: {weather.get('main', 'Unknown')}",
                description=(
                    f"{weather.get('description', '')}. "
                    f"Temp: {main.get('temp')}°C, Wind: {wind.get('speed')} m/s"
                ),
                raw_data=data,
                source_url=f"{base_url}?lat={city['lat']}&lon={city['lon']}",
                tags=["weather", weather.get("main", "unknown").lower()],
            )
            events.append(event)

        return events

    @staticmethod
    def _map_severity(weather: dict, wind: dict) -> str:
        wid = weather.get("id", 800)
        wind_speed = wind.get("speed") or 0
        # Thunderstorm or extreme
        if 200 <= wid < 300 or wid >= 960:
            return "critical" if wid >= 960 else "high"
        # Heavy rain, snow, squall, tornado
        if wid in (503, 504, 511, 602, 622, 771, 781):
            return "high"
        if wind_speed > 20:  # ~gale force
            return "high"
        if wind_speed > 10:
            return "medium"
        if wid in (500, 501, 502, 601, 611, 621):
            return "medium"
        return "low"


# ─────────────────────────────────────────────────────────────────────────────
# 5. NewsAPI
# ─────────────────────────────────────────────────────────────────────────────

class NewsAPIWorker(FeedWorker):
    """Ingests top headlines from NewsAPI."""

    SOURCE = "newsapi"
    URL = "https://newsapi.org/v2/top-headlines"

    def __init__(
        self,
        interval: int = 900,
        http_timeout: int = 30,
        country: str = "de",
        category: Optional[str] = None,
    ):
        super().__init__(interval=interval, http_timeout=http_timeout)
        self.api_key = os.getenv("NEWSAPI_KEY")
        self.country = country
        self.category = category

    async def fetch(self) -> List[StandardEvent]:
        if not self.api_key:
            logger.warning("NewsAPIWorker: NEWSAPI_KEY not set; skipping.")
            return []

        params: dict[str, Any] = {"country": self.country, "apiKey": self.api_key}
        if self.category:
            params["category"] = self.category

        try:
            resp = await self.client.get(self.URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("NewsAPI fetch failed: %s", exc)
            return []

        events: List[StandardEvent] = []
        for article in data.get("articles", []):
            ts = _parse_iso_timestamp(article.get("publishedAt"))
            severity = _map_generic_severity(
                f"{article.get('title', '')} {article.get('description', '')}"
            )

            event = StandardEvent(
                source=self.SOURCE,
                event_type="news_headline",
                timestamp=ts,
                severity=severity,
                confidence=0.7,
                title=article.get("title", ""),
                description=article.get("description", ""),
                raw_data=article,
                source_url=article.get("url") or self.URL,
                tags=[
                    "news",
                    article.get("source", {})
                    .get("name", "unknown")
                    .lower()
                    .replace(" ", "_"),
                ],
            )
            events.append(event)
        return events


# ─────────────────────────────────────────────────────────────────────────────
# 6. Bluesky
# ─────────────────────────────────────────────────────────────────────────────

class BlueskyWorker(FeedWorker):
    """Ingests public posts from Bluesky (AT Protocol) via the unauthenticated search API."""

    SOURCE = "bluesky"
    URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

    def __init__(
        self,
        interval: int = 300,
        http_timeout: int = 30,
        query: str = "logistics freight supply chain",
    ):
        super().__init__(interval=interval, http_timeout=http_timeout)
        self.query = query

    async def fetch(self) -> List[StandardEvent]:
        params = {"q": self.query, "limit": 50, "sort": "latest"}
        try:
            resp = await self.client.get(self.URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Bluesky fetch failed: %s", exc)
            return []

        events: List[StandardEvent] = []
        for post in data.get("posts", []):
            record = post.get("record", {})
            author = post.get("author", {})
            ts = _parse_iso_timestamp(record.get("createdAt"))
            severity = _map_generic_severity(record.get("text", ""))

            # Build a canonical bsky.app URL from the AT URI if possible
            uri_tail = ""
            uri = post.get("uri", "")
            if uri:
                uri_tail = uri.split("/")[-1]
            handle = author.get("handle", "")
            post_url = f"https://bsky.app/profile/{handle}/post/{uri_tail}" if handle and uri_tail else self.URL

            event = StandardEvent(
                source=self.SOURCE,
                event_type="social_post",
                timestamp=ts,
                lat=None,
                lon=None,
                severity=severity,
                confidence=0.6,
                title=record.get("text", "")[:120],
                description=record.get("text", ""),
                raw_data=post,
                source_url=post_url,
                tags=["social", "bluesky", handle or "unknown"],
            )
            events.append(event)
        return events
