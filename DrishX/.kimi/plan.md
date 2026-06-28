# ARGUS v2.0 — Multi-Domain Intelligence Platform
## Comprehensive Implementation Plan

### Executive Summary
ARGUS evolves from a Sentinel-2 truck detector into a real-time, multi-domain situational awareness platform. It ingests open-source data feeds (traffic, weather, aviation, maritime, public safety, social signals, radio), visualizes them on a 3D globe, and employs both browser-side WebGPU AI (Transformers.js) and server-side LLM reasoning to autonomously correlate events, generate alerts, and provide natural-language intelligence briefings.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              BROWSER LAYER                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │  3D Globe   │  │  Tactical   │  │  AI Chat    │  │ WebGPU Inference│ │
│  │ (Cesium/Gl) │  │  Dashboard  │  │  Assistant  │  │ (Transformers)  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │ WebSocket / SSE
┌─────────────────────────────────────────────────────────────────────────┐
│                              API GATEWAY (FastAPI)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │  Ingestion  │  │   RAG /     │  │  Correlation│  │  Forecast &     │ │
│  │  Controller │  │   Vector DB │  │   Engine    │  │  Anomaly Engine │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA & AI LAYER                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │  PostgreSQL │  │  ChromaDB   │  │   Ollama    │  │  Redis Cache    │ │
│  │  + Timescale│  │  (Vectors)  │  │  (LLM/API)  │  │  + PubSub       │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Infrastructure & Foundation (Week 1)

### 1.1 Async Architecture Fix
- **Problem**: Current `/api/analyze` endpoint makes blocking SentinelHub and OSMnx calls inside async generators, freezing the event loop for all other clients.
- **Fix**: Wrap all blocking I/O (`ox.graph_from_point`, `catalog.search`, `req_sh.get_data`, `engine.detect_trucks`) in `asyncio.to_thread()` or `starlette.concurrency.run_in_threadpool`.
- **Impact**: Multiple users can run analyses and view dashboards simultaneously.

### 1.2 Database Persistence
- Replace in-memory `engine.history` with **PostgreSQL + TimescaleDB** for time-series detection data.
- Schema: `missions`, `detections`, `data_feeds`, `alerts`, `correlations`.
- Migration: Alembic.

### 1.3 Real-Time Transport
- Add **WebSocket** endpoint `/ws/intelligence` for push notifications (new detections, alerts, feed updates).
- Redis pub/sub as message broker between ingestion workers and WebSocket manager.

### 1.4 Docker Production Setup
- `docker-compose.yml` already created; add `postgres`, `redis`, `ollama` services.
- Healthchecks and restart policies.

---

## Phase 2: Data Ingestion Layer — Open Source Feeds (Week 2-3)

All sources are **public, legal, and open-access**. No private surveillance or unauthorized access.

### 2.1 Traffic & Logistics
| Source | Data | Endpoint / Method |
|--------|------|-------------------|
| TomTom Traffic API | Real-time flow, incidents | REST API (free tier) |
| HERE Traffic API | Congestion, road closures | REST API |
| OpenStreetMap | Road networks | Existing OSMnx integration |
| Waze CCP | Citizen-reported incidents | Partner API |

### 2.2 Satellite & Remote Sensing
| Source | Data | Method |
|--------|------|--------|
| Copernicus Data Space | S2 imagery, truck detection | **Existing** SentinelHub |
| NASA FIRMS | Active fire/hotspots | RSS / JSON API |
| USGS Earthquakes | Seismic events | USGS GeoJSON Feed |
| NOAA GOES | Weather imagery, hurricanes | AWS Open Data (S3) |

### 2.3 Weather & Environment
| Source | Data | Method |
|--------|------|--------|
| OpenWeatherMap | Current, forecasts, alerts | REST API |
| NOAA NWS API | Warnings, watches, advisories | REST API (US only) |
| WeatherAPI.com | Global conditions | REST API |

### 2.4 Aviation & Maritime
| Source | Data | Method |
|--------|------|--------|
| The OpenSky Network | ADS-B positions | REST API |
| ADS-B Exchange | Global flight tracking | API (community tier) |
| AISHub / MarineTraffic | Vessel positions | AIS TCP stream or API |

### 2.5 Public Safety & Government Open Data
| Source | Data | Method |
|--------|------|--------|
| USGS Earthquake Hazards | Real-time quakes | GeoJSON feed |
| NOAA Alerts | Severe weather, tsunamis | CAP/XML ATOM feed |
| FEMA Open Data | Disaster declarations | Socrata API |
| Local Police Open Data | Crime blotters (anonymized) | Socrata / CKAN portals |
| NSOPW API | Sex offender registry (public) | Official DOJ API |

### 2.6 Social & News Signals
| Source | Data | Method |
|--------|------|--------|
| Bluesky (AT Protocol) | Public posts, firehose | Jetstream/WebSocket |
| Reddit | Public subreddit posts | Reddit API / Pushshift |
| GDELT Project | Global news, events, sentiment | BigQuery / CSV exports |
| NewsAPI | Headlines by topic/region | REST API |

### 2.7 Radio & Signal Monitoring (Public Receivers)
| Source | Data | Method |
|--------|------|--------|
| WebSDR / KiwiSDR | Public SDR receivers worldwide | Web scraping / JSON status |
| FAA ATC LiveATC | Air traffic control audio | Feeds (educational use) |
| APRS.fi | Amateur radio position reports | REST API |

### 2.8 Ingestion Worker Pattern
Each feed gets an async `FeedWorker` class:
```python
class FeedWorker:
    source: str
    interval: int  # seconds
    async def fetch(self) -> List[RawEvent]
    async def normalize(self, raw) -> StandardEvent
    async def ingest(self, events)
```
Workers run via `asyncio.gather()` in a dedicated supervisor process.

---

## Phase 3: AI/ML Engine (Week 3-4)

### 3.1 Browser-Side WebGPU Inference (Transformers.js v4)
**Purpose**: Privacy-preserving, zero-latency classification and embedding directly in the user's browser.

**Models to deploy**:
| Task | Model | Size | Use Case |
|------|-------|------|----------|
| Sentiment Analysis | `Xenova/distilbert-base-uncased-finetuned-sst-2-english` | ~66MB | Assess urgency of news/social posts |
| NER / Entity Extraction | `Xenova/bert-base-NER` | ~430MB | Extract locations, organizations from feeds |
| Text Embedding | `Xenova/all-MiniLM-L6-v2` | ~80MB | Semantic search across ingested documents |
| Zero-Shot Classification | `Xenova/nli-deberta-v3-small` | ~300MB | Classify alerts by severity without training |

**Implementation**:
- Load models in a Web Worker to avoid blocking UI.
- Cache model weights in IndexedDB after first download.
- Fallback to WASM backend if WebGPU unavailable.
- Send embeddings to backend for vector DB storage.

### 3.2 Server-Side LLM Reasoning (Ollama)
- Deploy `llama3.1:8b` or `qwen2.5:7b` via Ollama container.
- **RAG Pipeline**:
  1. User asks: "What anomalies near Frankfurt in the last 24h?"
  2. Embed query via MiniLM (browser or server).
  3. Retrieve top-K chunks from ChromaDB (detections, news, alerts).
  4. Construct prompt with retrieved context + system instructions.
  5. Generate structured JSON response with assumptions, correlations, predictions.

### 3.3 Autonomous Correlation Engine
Runs on a schedule (every 5 minutes) or triggered by new data:
1. **Spatial correlation**: Events within X km of each other.
2. **Temporal correlation**: Events within Y hours of each other.
3. **Semantic correlation**: Similar embeddings (cosine similarity > 0.85).
4. **Causal inference**: LLM judges if Event A likely influences Event B.

Output: `Correlation` objects with confidence scores, displayed as linked nodes on the globe.

---

## Phase 4: 3D Globe Visualization (Week 4)

### Option A: CesiumJS (Recommended for Geospatial Accuracy)
- **Pros**: True WGS84 globe, terrain elevation, 3D Tiles, time-dynamic visualization, KML/GeoJSON/CZML native support, excellent for aerospace/defense use cases.
- **Cons**: Larger bundle (~2MB), steeper learning curve, requires Cesium Ion token for high-res imagery (free tier available).
- **Best for**: Users who need terrain-aware analysis, 3D building visualization, and precise measurement tools.

### Option B: Globe.gl (Recommended for Speed & Integration)
- **Pros**: Lightweight (~300KB), declarative API, easy to layer on existing Leaflet data, excellent performance for large point datasets, beautiful arcs and hex bins.
- **Cons**: Flat sphere (no terrain), less precise for geodetic calculations.
- **Best for**: Rapid deployment, traffic flow visualization, detection density heatmaps on a sphere.

### Option C: deck.gl + MapLibre GL JS (Performance King)
- **Pros**: Handles millions of points, MVT support, excellent Core Web Vitals, WebGPU-ready.
- **Cons**: Globe view is experimental, no true terrain.
- **Best for**: Massive-scale data (millions of ADS-B points, AIS vessels).

### Recommended Hybrid Approach
- **Primary**: CesiumJS for the main 3D situational awareness view.
- **Overlay**: deck.gl layer inside Cesium for massive point rendering (if needed).
- **Fallback**: 2D Leaflet remains for quick tactical analysis.

---

## Phase 5: Autonomous AI Assistant (Week 4-5)

### 5.1 Real-Time Alert Generation
The assistant continuously monitors all feeds and generates alerts when:
- Satellite detects trucks + nearby traffic incident + weather advisory → **Compound Alert**
- ADS-B aircraft deviates from corridor + seismic event in region → **Correlation Alert**
- Social media spike in location + news coverage + government advisory → **Sentiment Alert**

Alert JSON schema:
```json
{
  "alert_id": "alt_001",
  "severity": "HIGH",
  "confidence": 0.91,
  "assumptions": ["Truck volume spike suggests supply chain disruption"],
  "correlations": [{"event_a": "traffic_incident", "event_b": "truck_spike", "relation": "causal"}],
  "predictions": ["Delays expected to continue 4-6 hours"],
  "recommended_action": "Reroute via A7 corridor"
}
```

### 5.2 Natural Language Interface
- Chat panel in the UI (similar to ChatGPT but contextual to the map).
- Pre-loaded prompt templates: "Summarize anomalies", "Predict next 48h", "Explain this detection".
- Voice input via Web Speech API + Whisper Tiny (Transformers.js) for hands-free operation.

---

## Phase 6: Security, Ethics & Compliance

1. **Data Provenance**: Every ingested event stores its source URL, fetch time, and license.
2. **Privacy by Design**: No individual tracking. Aggregate-only for sensitive feeds (crime, registries).
3. **Rate Limiting**: Per-IP and per-API-key limits on all endpoints.
4. **Audit Logging**: All AI assistant queries and alert dismissals are logged.
5. **Content Filtering**: LLM outputs are scanned for harmful content before display.

---

## Agent Swarm Assignment

| Agent | Task | Parallel |
|-------|------|----------|
| **Infrastructure Agent** | PostgreSQL schema, migrations, Docker, async fixes | Week 1 |
| **Ingestion Agent** | Feed workers (traffic, weather, ADS-B, AIS, news, social) | Week 2-3 |
| **AI Engine Agent** | Transformers.js integration, Ollama RAG, vector DB, correlation | Week 3-4 |
| **Globe Agent** | CesiumJS integration, layer system, time slider, 3D tiles | Week 4 |
| **Frontend Agent** | Chat UI, alert panel, notification system, responsive polish | Week 4-5 |
| **Safety Agent** | Content filters, audit logs, rate limiting, documentation | Week 5 |

---

## Open Questions for User

1. **3D Globe**: CesiumJS (terrain-accurate, heavier) vs Globe.gl (lightweight, faster) vs deck.gl (massive data)?
2. **LLM Backend**: Local Ollama (privacy, no cost) or OpenAI/Anthropic API (better reasoning, higher cost)?
3. **Data Scope**: Focus on North America/Europe first, or global from day one?
