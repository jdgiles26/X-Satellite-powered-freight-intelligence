/**
 * DrishX Tactical Command Terminal v1.0.0
 */

class DrishXDashboard {
    constructor() {
        this.map = null;
        this.chart = null;
        this.markers = {};
        this.roadLayer = null;
        this.sites = [];
        this.currentView = 'dashboard';
        this.isSatellite = false;
        this.selectedMissionIds = new Set();
        this.allMissions = [];
        this.allMissionsFetched = false;
        this.corridorLayer = null;
        this.anomalyMarkers = [];
        this.forecastEnabled = false;
        this.corridorsEnabled = false;
        this.heatmapEnabled = false;
        this.heatmapLayer = null;
        this.missionHistory = [];
        this.globe = null;

        this.init();
    }

    async init() {
        console.log("Initializing DrishX Operational Link...");
        this.setupMap();
        this.setupEventListeners();
        this.setupGlobe();

        // Initial data fetch
        await this.fetchSites();

        // Boot Auth (BYOK check)
        this.checkStoredCredentials();

        // ARGUS Intelligence Chat
        this.aiChat = new AIChatPanel();
    }

    setupMap() {
        // Use the German A2 (Fisser et al. Validation Site) as default view
        const testArea = [52.345, 10.550];
        this.map = L.map('main-map', {
            center: testArea,
            zoom: 14,
            zoomControl: false,
            attributionControl: false
        });

        this.updateBasemap();

        L.control.zoom({ position: 'bottomright' }).addTo(this.map);

        // Initialize drawing layer
        this.drawnItems = new L.FeatureGroup();
        this.map.addLayer(this.drawnItems);

        this.drawControl = new L.Control.Draw({
            draw: {
                polygon: false,
                marker: false,
                circle: false,
                circlemarker: false,
                polyline: false,
                rectangle: {
                    shapeOptions: {
                        color: 'var(--accent-blue)',
                        weight: 2
                    }
                }
            },
            edit: {
                featureGroup: this.drawnItems,
                remove: true
            }
        });

        this.map.on(L.Draw.Event.CREATED, (e) => {
            const layer = e.layer;
            this.drawnItems.clearLayers();
            this.drawnItems.addLayer(layer);
            const bbox = layer.getBounds();
            this.handleAOISelection(bbox);
        });
    }

    updateBasemap() {
        if (this.currentBasemap) this.map.removeLayer(this.currentBasemap);

        const url = this.isSatellite
            ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
            : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';

        this.currentBasemap = L.tileLayer(url, {
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(this.map);
    }

    setupGlobe() {
        try {
            this.globe = new GlobeView('globe-container');
            this.globe.init();
        } catch (e) {
            console.error('Failed to initialize globe:', e);
        }
    }

    setupEventListeners() {
        // AOI Selector
        document.getElementById('draw-aoi')?.addEventListener('click', () => {
            const rectDrawer = new L.Draw.Rectangle(this.map, this.drawControl.options.draw.rectangle);
            rectDrawer.enable();
            this.notify("Select an area on the map to analyze.", "info");
        });

        // Satellite Toggle
        document.getElementById('toggle-satellite')?.addEventListener('click', () => {
            this.isSatellite = !this.isSatellite;
            this.updateBasemap();
            this.notify(`Basemap switched to ${this.isSatellite ? 'Satellite' : 'Dark Mode'}`, "info");
        });

        // Navigation
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const view = e.currentTarget.dataset.view;
                this.switchView(view);
            });
        });

        // Corridor toggle
        document.getElementById('toggle-corridors')?.addEventListener('click', () => {
            this.corridorsEnabled = !this.corridorsEnabled;
            if (this.corridorsEnabled) {
                this.fetchAndRenderCorridors();
                this.notify("Corridor layer enabled.", "info");
            } else {
                this.clearCorridorLayer();
                this.notify("Corridor layer disabled.", "info");
            }
        });

        // Anomaly refresh
        document.getElementById('refresh-anomalies')?.addEventListener('click', () => {
            this.fetchAnomalies();
            this.notify("Anomaly scan dispatched.", "info");
        });

        // Forecast toggle
        document.getElementById('toggle-forecast')?.addEventListener('click', () => {
            this.forecastEnabled = !this.forecastEnabled;
            const btn = document.getElementById('toggle-forecast');
            btn.textContent = this.forecastEnabled ? 'Hide Forecast' : 'Show Forecast';
            if (this.forecastEnabled) {
                this.updateForecast();
            } else {
                this.clearForecastChart();
            }
        });

        // Forecast horizon change
        document.getElementById('forecast-horizon')?.addEventListener('change', () => {
            if (this.forecastEnabled) this.updateForecast();
        });

        // Trends Controls
        document.getElementById('refresh-trends')?.addEventListener('click', () => this.updateTrends());

        // Initialize Flatpickr for better calendar experience
        const fpConfig = {
            theme: "dark",
            dateFormat: "Y-m-d",
            onChange: () => this.updateTrends()
        };

        flatpickr("#trend-from", fpConfig);
        flatpickr("#trend-to", fpConfig);

        // Search Bar
        const searchBtn = document.getElementById('execute-search');
        const searchInput = document.getElementById('map-search-input');

        searchBtn?.addEventListener('click', () => this.handleLocationSearch());
        searchInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.handleLocationSearch();
        });

        // Close Overlays
        document.querySelector('.close-overlay')?.addEventListener('click', () => {
            document.getElementById('site-overlay').classList.add('hidden');
        });

        document.getElementById('close-intel')?.addEventListener('click', () => {
            document.getElementById('intel-drawer').classList.add('hidden');
        });

        // Copernicus Auth Link (BYOK)
        document.getElementById('save-auth')?.addEventListener('click', () => this.handleAuthSave());

        // Mobile menu
        document.getElementById('mobile-menu-toggle')?.addEventListener('click', () => this.toggleMobileSidebar());
        document.getElementById('sidebar-overlay')?.addEventListener('click', () => this.toggleMobileSidebar());

        // History refresh
        document.getElementById('refresh-history')?.addEventListener('click', () => this.renderMissionHistory());

        // Shortcuts modal
        document.getElementById('shortcuts-btn')?.addEventListener('click', () => {
            document.getElementById('shortcuts-modal').classList.remove('hidden');
        });

        // Close heatmap legend
        document.getElementById('close-heatmap-legend')?.addEventListener('click', () => {
            document.getElementById('heatmap-legend').classList.add('hidden');
            this.heatmapEnabled = false;
            this.clearHeatmapLayer();
        });

        // Globe controls
        document.getElementById('toggle-globe-detections')?.addEventListener('click', () => {
            this.globe?.toggleLayer('detections');
            this.notify('Globe detections toggled.', 'info');
        });
        document.getElementById('toggle-globe-feeds')?.addEventListener('click', () => {
            this.globe?.toggleLayer('feeds');
            this.notify('Globe feeds toggled.', 'info');
        });
        document.getElementById('toggle-globe-corridors')?.addEventListener('click', () => {
            this.globe?.toggleLayer('corridors');
            this.notify('Globe corridors toggled.', 'info');
        });

        // Keyboard shortcuts
        this.setupKeyboardShortcuts();

        // Responsive handler
        window.addEventListener('resize', () => this.handleResize());
        this.handleResize();
    }

    async handleLocationSearch() {
        const query = document.getElementById('map-search-input').value;
        if (!query) return;

        const dropdown = document.getElementById('search-results-dropdown');
        dropdown.innerHTML = '<div class="search-result"><span class="main-text">Querying satellites...</span></div>';
        dropdown.classList.remove('hidden');

        try {
            const resp = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5`);
            const results = await resp.json();

            if (results.length === 0) {
                dropdown.innerHTML = '<div class="search-result"><span class="main-text">No sectors found.</span></div>';
                return;
            }

            dropdown.innerHTML = results.map(res => `
                <div class="search-result" onclick="window.dashboard.jumpToLocation(${res.lat}, ${res.lon}, '${res.display_name.split(',')[0]}')">
                    <span class="main-text">${res.display_name.split(',')[0]}</span>
                    <span class="sub-text">${res.display_name.split(',').slice(1).join(',')}</span>
                </div>
            `).join('');

        } catch (e) {
            this.notify("Search engine offline.", "error");
            dropdown.classList.add('hidden');
        }
    }

    jumpToLocation(lat, lon, label) {
        this.map.flyTo([lat, lon], 15, { duration: 1.5 });
        document.getElementById('search-results-dropdown').classList.add('hidden');
        this.notify(`Navigating to sector: ${label}`, "info");

        // Brief highlight
        const circle = L.circle([lat, lon], {
            radius: 500,
            color: 'var(--accent-blue)',
            fillColor: 'var(--accent-blue)',
            fillOpacity: 0.1,
            dashArray: '5, 10'
        }).addTo(this.map);

        setTimeout(() => this.map.removeLayer(circle), 3000);
    }

    switchView(view) {
        this.currentView = view;
        document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
        document.getElementById(`${view}-view`)?.classList.remove('hidden');

        // Update tabs
        document.querySelectorAll('.nav-item').forEach(btn => {
            const btnView = btn.dataset.view;
            btn.classList.toggle('active', btnView === view);
        });

        if (view === 'trends') {
            this.updateTrends();
            if (this.forecastEnabled) this.updateForecast();
        }
        if (view === 'anomalies') {
            this.fetchAnomalies();
        }
        if (view === 'history') {
            this.renderMissionHistory();
        }
        if (view === 'globe') {
            this.populateGlobe();
        }

        // Close mobile sidebar
        document.querySelector('.sidebar')?.classList.remove('open');
        document.getElementById('sidebar-overlay')?.classList.remove('active');

        // Update header
        const titles = {
            dashboard: 'Operations',
            trends: 'Tactical Trends',
            anomalies: 'Anomaly Intelligence',
            history: 'Mission History',
            settings: 'Copernicus Link',
            globe: 'Orbital View'
        };
        const titleEl = document.querySelector('.top-header h1');
        if (titleEl && titles[view]) titleEl.textContent = titles[view];
    }

    async updateTrends() {
        const fromDate = document.getElementById('trend-from').value;
        const toDate = document.getElementById('trend-to').value;
        const siteIdsArray = Array.from(this.selectedMissionIds || []);
        const siteIds = siteIdsArray.join(',');

        try {
            const resp = await fetch(`/api/analytics/trends?from_date=${fromDate}&to_date=${toDate}${siteIds ? `&site_ids=${siteIds}` : ''}`);
            const data = await resp.json();

            // Update stats
            document.getElementById('stat-total').textContent = data.summary.total_detections;
            document.getElementById('stat-peak').textContent = data.summary.missions_count + " Sectors";
            document.getElementById('stat-avg').textContent = data.datasets.length;

            this.renderTrendChart(data);
            this.updateMissionSelector();
        } catch (e) {
            console.error("Trends fetch error:", e);
            this.notify("Failed to sync historical trends.", "error");
        }
    }

    updateMissionSelector() {
        const container = document.getElementById('mission-comparison-selector');
        if (!container) return;

        if (this.allMissionsFetched) {
            this.renderMissionChecklist(container);
            return;
        }

        fetch('/api/sites').then(r => r.json()).then(sites => {
            this.allMissions = sites.filter(s => s.type === 'history');
            this.allMissionsFetched = true;
            this.renderMissionChecklist(container);
        });
    }

    renderMissionChecklist(container) {
        if (!this.selectedMissionIds) this.selectedMissionIds = new Set();

        container.innerHTML = this.allMissions.map((m, i) => {
            const isActive = this.selectedMissionIds.has(m.id);
            const colors = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#a855f7", "#ec4899"];
            const color = colors[i % colors.length];

            return `
                <div class="comparison-item ${isActive ? 'active' : ''}" onclick="window.dashboard.toggleMissionComparison('${m.id}')">
                    <span class="color-dot" style="background: ${color}"></span>
                    <span>${m.name}</span>
                </div>
            `;
        }).join('');
    }

    toggleMissionComparison(id) {
        if (!this.selectedMissionIds) this.selectedMissionIds = new Set();
        if (this.selectedMissionIds.has(id)) {
            this.selectedMissionIds.delete(id);
        } else {
            this.selectedMissionIds.add(id);
        }
        this.updateTrends();
    }

    renderTrendChart(data) {
        const ctx = document.getElementById('trend-chart')?.getContext('2d');
        if (!ctx) return;

        if (this.trendChartInstance) {
            this.trendChartInstance.destroy();
        }

        this.trendChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: data.datasets.map(ds => ({
                    ...ds,
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: ds.borderColor
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        labels: { color: '#94a3b8', boxWidth: 12, padding: 20 }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: '#1e293b',
                        titleColor: '#94a3b8',
                        bodyColor: '#fff',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1
                    }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    }
                }
            }
        });
    }

    async handleAOISelection(bounds, siteId = 'custom', siteName = null) {
        const sw = bounds instanceof L.LatLngBounds ? bounds.getSouthWest() : { lat: bounds[0], lng: bounds[1] };
        const ne = bounds instanceof L.LatLngBounds ? bounds.getNorthEast() : { lat: bounds[2], lng: bounds[3] };
        const bbox = bounds instanceof L.LatLngBounds ? [sw.lat, sw.lng, ne.lat, ne.lng] : bounds;

        // Prepare HUD
        const hud = document.getElementById('progress-hud');
        const progressBar = document.getElementById('hud-progress-bar');
        const stepText = document.getElementById('hud-step-text');
        const percentText = document.getElementById('hud-percent-text');
        const logConsole = document.getElementById('hud-log');

        hud.classList.remove('hidden');
        progressBar.style.width = '0%';
        stepText.innerText = "Initializing mission...";
        percentText.innerText = "0%";
        logConsole.innerHTML = '';

        const appendLog = (msg) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `
                <span class="time">[${new Date().toLocaleTimeString()}]</span>
                <span class="indicator">»</span>
                <span class="msg">${msg}</span>
            `;
            logConsole.appendChild(entry);
            logConsole.scrollTop = logConsole.scrollHeight;
        };

        const months = parseInt(document.getElementById('mission-months')?.value || 4);
        const frames = parseInt(document.getElementById('mission-frames')?.value || 10);
        const label = siteName ? `Mission: ${siteName}` : `Analysis Area ${new Date().toLocaleTimeString()} (${months}mo, ${frames}fr)`;

        try {
            const resp = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    bbox: bbox,
                    label: label,
                    months: months,
                    max_frames: frames,
                    site_id: siteId
                })
            });

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep partial line in buffer

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const evt = JSON.parse(line);

                        if (evt.type === 'progress') {
                            progressBar.style.width = `${evt.percent}%`;
                            percentText.innerText = `${evt.percent}%`;
                            stepText.innerText = evt.message;
                            appendLog(evt.message);
                        } else if (evt.type === 'result') {
                            appendLog("Mission complete. Synchronizing results...");
                            this.notify(evt.message, "success");

                            // Successful finish
                            setTimeout(() => {
                                hud.classList.add('hidden');
                                this.fetchRoads(bbox);
                                this.fetchSites();

                                // Show observation markers if available
                                if (evt.mission_id) {
                                    this.loadMissionMarkers(evt.mission_id);
                                }
                            }, 1500);
                        } else if (evt.type === 'error') {
                            this.notify(evt.status === 'error' ? evt.message : "Analysis failed.", "error");
                            appendLog(`ERROR: ${evt.message}`);
                            setTimeout(() => hud.classList.add('hidden'), 3000);
                        }
                    } catch (err) {
                        console.error("Parse error in stream:", err);
                    }
                }
            }
        } catch (e) {
            this.notify("Network error in satellite link.", "error");
            appendLog("CRITICAL: Connection timed out.");
            setTimeout(() => hud.classList.add('hidden'), 3000);
        }
    }

    async fetchRoads(bbox) {
        try {
            const [minLat, minLon, maxLat, maxLon] = bbox;
            const resp = await fetch(`/api/roads?min_lat=${minLat}&min_lon=${minLon}&max_lat=${maxLat}&max_lon=${maxLon}`);
            const geojson = await resp.json();
            this.renderRoads(geojson);
        } catch (e) {
            console.error("Failed to fetch roads:", e);
        }
    }

    renderRoads(geojson) {
        if (this.roadLayer) this.map.removeLayer(this.roadLayer);

        this.roadLayer = L.geoJSON(geojson, {
            style: {
                color: 'var(--accent-amber)',
                weight: 3,
                opacity: 0.6,
                dashArray: '5, 5'
            }
        }).addTo(this.map);

        this.notify("Road corridors identified and highlighted.", "info");
    }

    async loadMissionMarkers(missionId) {
        try {
            const resp = await fetch(`/api/detections/${missionId}`);
            const detections = await resp.json();
            this.renderObservationMarkers(detections);
        } catch (e) {
            console.error("Failed to load mission markers:", e);
        }
    }

    renderObservationMarkers(detections) {
        // Clear existing observation markers
        if (this.obsMarkers) {
            this.obsMarkers.forEach(m => this.map.removeLayer(m));
        }
        this.obsMarkers = [];

        detections.forEach(d => {
            const marker = L.marker([d.lat, d.lon], {
                icon: L.divIcon({
                    className: 'observation-pip',
                    html: '<div class="pip-core"></div>',
                    iconSize: [12, 12],
                    iconAnchor: [6, 6]
                })
            }).addTo(this.map);

            marker.on('click', () => {
                this.showDetectionIntel(d);
                this.map.setView([d.lat, d.lon], 18);
            });

            this.obsMarkers.push(marker);
        });

        if (detections.length > 0) {
            this.notify(`Mapped ${detections.length} tactical detections.`, "success");
        }
    }

    showDetectionIntel(d) {
        const drawer = document.getElementById('intel-drawer');
        const content = document.getElementById('intel-content');
        if (!drawer || !content) return;

        drawer.classList.remove('hidden');
        content.innerHTML = `
            <div class="intel-profile">
                <div class="multispectral-view">
                    <img src="${d.image_url}" alt="Target Signature">
                </div>
                <div class="telemetry-grid">
                    <div class="tel-item">
                        <span class="hud-label">Sensed Domain</span>
                        <span class="tel-value">${new Date(d.timestamp).toLocaleDateString()}</span>
                    </div>
                    <div class="tel-item">
                        <span class="hud-label">Time (UTC)</span>
                        <span class="tel-value">${new Date(d.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <div class="tel-item accent-blue">
                        <span class="hud-label">Logistics Speed</span>
                        <span class="tel-value">${d.speed_kmh} KM/H</span>
                    </div>
                    <div class="tel-item">
                        <span class="hud-label">Heading Vector</span>
                        <span class="tel-value">${d.heading}°</span>
                    </div>
                    <div class="tel-item">
                        <span class="hud-label">Coords</span>
                        <span class="tel-value">${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}</span>
                    </div>
                    <div class="tel-item highlight-amber">
                        <span class="hud-label">Spectral Conf.</span>
                        <span class="tel-value">${(d.confidence * 100).toFixed(1)}%</span>
                    </div>
                </div>
                <button class="btn btn-hud-primary btn-sm" onclick="window.dashboard.explainDetection('${d._mission_id || 'unknown'}', '${d.id}')">
                    <i class="fas fa-brain"></i> Explain Detection
                </button>
                <div id="xai-explanation-panel" class="xai-panel hidden"></div>
            </div>
        `;
    }

    async explainDetection(missionId, detectionId) {
        const panel = document.getElementById('xai-explanation-panel');
        if (!panel) return;
        panel.classList.remove('hidden');
        panel.innerHTML = '<div class="loading-state"><i class="fas fa-spinner fa-spin"></i> Computing spectral explanation...</div>';

        try {
            const resp = await fetch(`/api/detections/${missionId}/${detectionId}/explain`);
            const data = await resp.json();

            if (data.error || data.method === 'unavailable') {
                panel.innerHTML = '<div class="xai-error">Explanation unavailable for this detection.</div>';
                return;
            }

            const contributions = data.contributions || [];
            const bars = contributions.slice(0, 5).map(c => {
                const width = Math.min(c.percentage, 100);
                return `
                    <div class="xai-bar-row">
                        <span class="xai-bar-label">${c.feature}</span>
                        <div class="xai-bar-track">
                            <div class="xai-bar-fill" style="width: ${width}%"></div>
                        </div>
                        <span class="xai-bar-value">${c.percentage}%</span>
                    </div>
                `;
            }).join('');

            panel.innerHTML = `
                <div class="xai-header">
                    <i class="fas fa-microscope"></i> Spectral Explanation
                    <span class="xai-method">${data.method}</span>
                </div>
                <div class="xai-top-driver">
                    <span class="hud-label">Primary Driver</span>
                    <span class="xai-driver-value">${data.top_driver || 'N/A'}</span>
                </div>
                <div class="xai-bars">${bars}</div>
                <div class="xai-signature">
                    <span class="hud-label">Feature Signature</span>
                    <code>${JSON.stringify(data.signature || {}, null, 2)}</code>
                </div>
            `;
        } catch (e) {
            panel.innerHTML = '<div class="xai-error">Failed to load explanation.</div>';
        }
    }

    async fetchAnomalies() {
        try {
            const [anomaliesResp, summaryResp] = await Promise.all([
                fetch('/api/analytics/anomalies'),
                fetch('/api/analytics/anomalies/summary')
            ]);
            const anomalies = await anomaliesResp.json();
            const summary = await summaryResp.json();

            this.renderAnomalyFeed(anomalies);
            this.renderAnomalySummary(summary);
            this.renderAnomalyMarkers(anomalies);

            // Update sidebar badge
            const badge = document.getElementById('anomaly-badge');
            const countEl = document.getElementById('anomaly-count');
            if (badge && countEl) {
                const total = summary.total_anomalies || 0;
                if (total > 0) {
                    badge.classList.remove('hidden');
                    countEl.textContent = `${total} Alert${total !== 1 ? 's' : ''}`;
                } else {
                    badge.classList.add('hidden');
                }
            }
        } catch (e) {
            console.error("Failed to fetch anomalies:", e);
        }
    }

    renderAnomalySummary(summary) {
        const totalEl = document.getElementById('summary-total');
        const critEl = document.getElementById('summary-critical');
        const highEl = document.getElementById('summary-high');
        if (totalEl) totalEl.textContent = summary.total_anomalies || 0;
        if (critEl) critEl.textContent = summary.critical_count || 0;
        if (highEl) highEl.textContent = summary.high_count || 0;
    }

    renderAnomalyFeed(anomalies) {
        const container = document.getElementById('anomaly-feed');
        if (!container) return;

        if (!anomalies || anomalies.length === 0) {
            container.innerHTML = '<div class="loading-state">No anomalies detected. Freight patterns appear nominal.</div>';
            return;
        }

        container.innerHTML = anomalies.slice(0, 50).map(a => `
            <div class="anomaly-card severity-${a.severity?.toLowerCase() || 'low'}">
                <div class="anomaly-header">
                    <span class="anomaly-type">${a.type.replace(/_/g, ' ').toUpperCase()}</span>
                    <span class="anomaly-severity" style="color: ${a.severity_color || '#10b981'}">${a.severity}</span>
                </div>
                <div class="anomaly-body">${a.description}</div>
                <div class="anomaly-meta">
                    <span>${a.mission_label}</span>
                    <span>${a.date}</span>
                </div>
            </div>
        `).join('');
    }

    renderAnomalyMarkers(anomalies) {
        // Clear existing
        if (this.anomalyMarkers) {
            this.anomalyMarkers.forEach(m => this.map.removeLayer(m));
        }
        this.anomalyMarkers = [];

        const severityColors = {
            CRITICAL: '#dc2626',
            HIGH: '#ef4444',
            MEDIUM: '#f59e0b',
            LOW: '#10b981',
        };

        (anomalies || []).forEach(a => {
            if (!a.lat || !a.lon) return;
            const color = severityColors[a.severity] || '#10b981';
            const marker = L.circleMarker([a.lat, a.lon], {
                radius: a.severity === 'CRITICAL' ? 8 : a.severity === 'HIGH' ? 6 : 4,
                color: color,
                fillColor: color,
                fillOpacity: 0.6,
                weight: 2,
            }).addTo(this.map);

            marker.bindTooltip(`<b>${a.type.replace(/_/g, ' ')}</b><br>${a.description}`, {
                direction: 'top',
                className: 'anomaly-tooltip'
            });

            this.anomalyMarkers.push(marker);
        });
    }

    async fetchAndRenderCorridors() {
        try {
            const resp = await fetch('/api/corridors');
            const geojson = await resp.json();
            this.renderCorridors(geojson);
        } catch (e) {
            console.error("Failed to fetch corridors:", e);
            this.notify("Corridor discovery failed.", "error");
        }
    }

    renderCorridors(geojson) {
        this.clearCorridorLayer();

        if (!geojson.features || geojson.features.length === 0) {
            this.notify("No corridors discovered yet. Run more missions.", "info");
            return;
        }

        this.corridorLayer = L.geoJSON(geojson, {
            style: (feature) => {
                const density = feature.properties.density_score || 0;
                const opacity = Math.min(0.3 + density * 0.1, 0.9);
                return {
                    color: '#00ff9d',
                    weight: 3 + Math.min(density, 5),
                    opacity: opacity,
                    dashArray: '10, 5',
                };
            },
            onEachFeature: (feature, layer) => {
                const p = feature.properties;
                layer.bindTooltip(`
                    <b>Corridor ${p.corridor_id}</b><br>
                    Detections: ${p.detection_count}<br>
                    Density: ${p.density_score}/km<br>
                    Heading: ${p.dominant_heading}°<br>
                    Avg Speed: ${p.avg_speed_kmh} km/h
                `, { className: 'corridor-tooltip' });
            }
        }).addTo(this.map);

        this.notify(`Discovered ${geojson.features.length} freight corridors.`, "success");
    }

    clearCorridorLayer() {
        if (this.corridorLayer) {
            this.map.removeLayer(this.corridorLayer);
            this.corridorLayer = null;
        }
    }

    async updateForecast() {
        const container = document.getElementById('forecast-viewport');
        const placeholder = document.getElementById('forecast-placeholder');
        if (placeholder) placeholder.classList.add('hidden');

        const horizon = parseInt(document.getElementById('forecast-horizon')?.value || 14);
        const siteIds = Array.from(this.selectedMissionIds || []).join(',');

        try {
            // Fetch forecasts for selected missions or all
            const forecasts = await Promise.all(
                (siteIds ? siteIds.split(',') : ['']).map(async (sid) => {
                    const url = sid
                        ? `/api/analytics/forecast?mission_id=${sid}&horizon_days=${horizon}`
                        : `/api/analytics/forecast?horizon_days=${horizon}`;
                    const resp = await fetch(url);
                    return resp.json();
                })
            );
            this.renderForecastChart(forecasts.flat());
        } catch (e) {
            console.error("Forecast fetch error:", e);
        }
    }

    renderForecastChart(forecasts) {
        const ctx = document.getElementById('forecast-chart')?.getContext('2d');
        if (!ctx) return;

        if (this.forecastChartInstance) {
            this.forecastChartInstance.destroy();
        }

        if (!forecasts || forecasts.length === 0) {
            document.getElementById('forecast-placeholder')?.classList.remove('hidden');
            return;
        }

        // Build datasets: historical solid, forecast dashed
        const datasets = [];
        const colors = ["#00f2ff", "#f59e0b", "#10b981", "#ef4444", "#a855f7"];

        forecasts.forEach((fc, i) => {
            const color = colors[i % colors.length];
            if (fc.historical_dates && fc.historical_values) {
                datasets.push({
                    label: `${fc.mission_label} (Historical)`,
                    data: fc.historical_values,
                    borderColor: color,
                    backgroundColor: color + '22',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.3,
                    pointRadius: 3,
                });
            }
            if (fc.dates && fc.forecast) {
                const allDates = [...(fc.historical_dates || []), ...fc.dates];
                const allValues = [...Array(fc.historical_values?.length || 0).fill(null), ...fc.forecast];
                datasets.push({
                    label: `${fc.mission_label} (Forecast)`,
                    data: allValues,
                    borderColor: color,
                    backgroundColor: color + '11',
                    borderWidth: 2,
                    borderDash: [6, 4],
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                });
            }
        });

        this.forecastChartInstance = new Chart(ctx, {
            type: 'line',
            data: { labels: forecasts[0]?.historical_dates?.concat(forecasts[0]?.dates || []) || [], datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#94a3b8', boxWidth: 12, padding: 15 } },
                    tooltip: {
                        backgroundColor: '#1e293b',
                        titleColor: '#94a3b8',
                        bodyColor: '#fff',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                    }
                },
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false }, ticks: { color: '#94a3b8' } },
                    x: { grid: { display: false }, ticks: { color: '#94a3b8', maxRotation: 45 } },
                }
            }
        });
    }

    clearForecastChart() {
        if (this.forecastChartInstance) {
            this.forecastChartInstance.destroy();
            this.forecastChartInstance = null;
        }
        document.getElementById('forecast-placeholder')?.classList.remove('hidden');
    }

    async fetchSites() {
        try {
            const resp = await fetch('/api/sites');
            this.sites = await resp.json();
            this.updateMarkers();
            // Cache mission data for heatmap and history
            this.allMissionsData = this.sites
                .filter(s => s.type === 'history')
                .map(s => ({ id: s.id, name: s.name, bbox: s.bbox, detections: [] }));
        } catch (e) {
            console.error("Failed to fetch sites:", e);
        }
    }

    updateMarkers() {
        Object.values(this.markers).forEach(m => this.map.removeLayer(m));
        this.markers = {};

        const icon = L.divIcon({
            className: 'custom-marker',
            html: '<div class="marker-pin"></div>',
            iconSize: [20, 20],
            iconAnchor: [10, 10]
        });

        this.sites.forEach(site => {
            const marker = L.marker([site.lat, site.lng], { icon })
                .addTo(this.map);

            const popupContent = document.createElement('div');
            popupContent.className = 'marker-popup';
            popupContent.innerHTML = `
                <div class="popup-title">${site.name}</div>
                <div class="popup-meta">${site.country} • ${site.type.toUpperCase()}</div>
                <div class="popup-actions">
                    <button class="btn btn-hud-primary btn-sm analyze-site-btn">Analyze Node</button>
                </div>
            `;

            popupContent.querySelector('.analyze-site-btn').onclick = () => {
                this.handleAOISelection(site.bbox, site.id, site.name);
                marker.closePopup();
            };
            popupContent.querySelector('.analyze-site-btn').addEventListener('mouseenter', () => {
                popupContent.querySelector('.analyze-site-btn').style.transform = 'translateY(-1px)';
            });
            popupContent.querySelector('.analyze-site-btn').addEventListener('mouseleave', () => {
                popupContent.querySelector('.analyze-site-btn').style.transform = 'translateY(0)';
            });

            marker.bindPopup(popupContent);
            marker.bindTooltip(`<b>${site.name}</b>`, { direction: 'top' });

            this.markers[site.id] = marker;
        });
    }

    notify(msg, type = 'info') {
        console.log(`[${type.toUpperCase()}] ${msg}`);
        this.showToast(msg, type);
        // Also update sidebar status
        const statusEl = document.querySelector('.status-indicator span:last-child');
        if (statusEl) {
            statusEl.textContent = msg;
            setTimeout(() => { statusEl.textContent = 'System Online'; }, 5000);
        }
    }

    showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const icons = { info: 'fa-info-circle', success: 'fa-check-circle', warning: 'fa-exclamation-triangle', error: 'fa-times-circle' };
        const titles = { info: 'Info', success: 'Success', warning: 'Warning', error: 'Error' };

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <i class="fas ${icons[type] || icons.info} toast-icon"></i>
            <div class="toast-content">
                <span class="toast-title">${titles[type] || 'Info'}</span>
                <span class="toast-message">${message}</span>
            </div>
            <button class="toast-close"><i class="fas fa-times"></i></button>
        `;
        toast.querySelector('.toast-close').addEventListener('click', () => {
            toast.classList.add('toast-exit');
            setTimeout(() => toast.remove(), 300);
        });
        container.appendChild(toast);
        setTimeout(() => {
            if (toast.parentElement) {
                toast.classList.add('toast-exit');
                setTimeout(() => toast.remove(), 300);
            }
        }, duration);
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            const key = e.key.toLowerCase();
            switch (key) {
                case '1': this.switchView('dashboard'); break;
                case '2': this.switchView('trends'); break;
                case '3': this.switchView('anomalies'); break;
                case '4': this.switchView('history'); break;
                case '5': this.switchView('settings'); break;
                case '6': this.switchView('globe'); break;
                case 'd': {
                    e.preventDefault();
                    const rectDrawer = new L.Draw.Rectangle(this.map, this.drawControl.options.draw.rectangle);
                    rectDrawer.enable();
                    this.showToast('Select an area on the map to analyze.', 'info');
                    break;
                }
                case 'l':
                    e.preventDefault();
                    this.isSatellite = !this.isSatellite;
                    this.updateBasemap();
                    this.showToast(`Basemap: ${this.isSatellite ? 'Satellite' : 'Dark Mode'}`, 'info');
                    break;
                case 'c':
                    e.preventDefault();
                    this.corridorsEnabled = !this.corridorsEnabled;
                    if (this.corridorsEnabled) {
                        this.fetchAndRenderCorridors();
                        this.showToast('Corridor layer enabled.', 'info');
                    } else {
                        this.clearCorridorLayer();
                        this.showToast('Corridor layer disabled.', 'info');
                    }
                    break;
                case 'h':
                    e.preventDefault();
                    this.toggleHeatmap();
                    break;
                case 'r':
                    e.preventDefault();
                    this.fetchAnomalies();
                    this.showToast('Anomaly scan dispatched.', 'info');
                    break;
                case '?':
                    e.preventDefault();
                    document.getElementById('shortcuts-modal').classList.remove('hidden');
                    break;
                case 'escape':
                    document.getElementById('shortcuts-modal').classList.add('hidden');
                    document.getElementById('intel-drawer').classList.add('hidden');
                    document.getElementById('site-overlay').classList.add('hidden');
                    document.getElementById('ai-chat-drawer').classList.add('hidden');
                    break;
            }
        });
    }

    toggleMobileSidebar() {
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        sidebar?.classList.toggle('open');
        overlay?.classList.toggle('active');
    }

    async populateGlobe() {
        if (!this.globe) return;
        try {
            // Fetch sites
            const sitesResp = await fetch('/api/sites');
            const sites = await sitesResp.json();
            const sitePoints = sites.map(s => ({
                lat: s.lat,
                lon: s.lng || s.lon,
                confidence: 0.8,
                name: s.name
            }));
            this.globe.renderDetections(sitePoints);

            // Fetch corridors
            const corridorsResp = await fetch('/api/corridors');
            const corridorsData = await corridorsResp.json();
            let corridorArcs = [];
            if (corridorsData.features) {
                corridorArcs = corridorsData.features.map(f => {
                    const coords = f.geometry?.coordinates || [];
                    if (coords.length >= 2) {
                        return {
                            start_lat: coords[0][1],
                            start_lng: coords[0][0],
                            end_lat: coords[coords.length - 1][1],
                            end_lng: coords[coords.length - 1][0]
                        };
                    }
                    return null;
                }).filter(Boolean);
            }
            this.globe.renderCorridors(corridorArcs);

            // Fetch recent anomalies as feeds
            const anomaliesResp = await fetch('/api/analytics/anomalies');
            const anomalies = await anomaliesResp.json();
            const feedPoints = (anomalies || []).map(a => ({
                lat: a.lat,
                lon: a.lon,
                severity: a.severity || 'LOW'
            })).filter(f => f.lat && f.lon);
            this.globe.renderFeeds(feedPoints);
        } catch (e) {
            console.error('Failed to populate globe:', e);
            this.notify('Globe data sync failed.', 'error');
        }
    }

    handleResize() {
        const isMobile = window.innerWidth <= 768;
        if (!isMobile) {
            document.querySelector('.sidebar')?.classList.remove('open');
            document.getElementById('sidebar-overlay')?.classList.remove('active');
        }
        if (this.globe) {
            this.globe.resize();
        }
    }

    toggleHeatmap() {
        this.heatmapEnabled = !this.heatmapEnabled;
        const legend = document.getElementById('heatmap-legend');
        if (this.heatmapEnabled) {
            this.renderHeatmap();
            legend?.classList.remove('hidden');
            this.showToast('Detection heatmap enabled.', 'info');
        } else {
            this.clearHeatmapLayer();
            legend?.classList.add('hidden');
            this.showToast('Heatmap disabled.', 'info');
        }
    }

    renderHeatmap() {
        this.clearHeatmapLayer();
        const allDets = [];
        for (const mission of this.allMissionsData || []) {
            for (const d of mission.detections || []) {
                allDets.push([d.lat, d.lon, d.confidence || 0.5]);
            }
        }
        if (allDets.length === 0) {
            this.showToast('No detection data for heatmap.', 'warning');
            this.heatmapEnabled = false;
            document.getElementById('heatmap-legend')?.classList.add('hidden');
            return;
        }
        // Simple Leaflet heatmap using circle markers if heatmap plugin not available
        this.heatmapLayer = L.layerGroup();
        allDets.forEach(([lat, lon, intensity]) => {
            const radius = 8 + intensity * 20;
            const marker = L.circleMarker([lat, lon], {
                radius: radius,
                fillColor: `rgba(0, 242, 255, ${0.15 + intensity * 0.3})`,
                color: 'transparent',
                fillOpacity: 0.6,
                weight: 0,
            }).addTo(this.heatmapLayer);
        });
        this.heatmapLayer.addTo(this.map);
    }

    clearHeatmapLayer() {
        if (this.heatmapLayer) {
            this.map.removeLayer(this.heatmapLayer);
            this.heatmapLayer = null;
        }
    }

    async renderMissionHistory() {
        const container = document.getElementById('mission-history-list');
        if (!container) return;
        container.innerHTML = '<div class="loading-state">Loading mission archive...</div>';

        try {
            const resp = await fetch('/api/sites');
            const sites = await resp.json();
            const history = sites.filter(s => s.type === 'history');
            // Preserve existing detection caches when rebuilding mission list
            const existing = new Map((this.allMissionsData || []).map(m => [m.id, m.detections]));
            this.allMissionsData = history.map(h => ({ ...h, detections: existing.get(h.id) || [] }));

            if (history.length === 0) {
                container.innerHTML = '<div class="loading-state">No missions in archive.</div>';
                return;
            }

            container.innerHTML = history.map(m => `
                <div class="mission-item" onclick="window.dashboard.focusMission('${m.id}')">
                    <div class="mission-info">
                        <span class="mission-name">${m.name}</span>
                        <span class="mission-meta">${m.id} • ${m.country}</span>
                    </div>
                    <div class="mission-actions" onclick="event.stopPropagation()">
                        <button class="btn-icon" title="Load on map" onclick="window.dashboard.focusMission('${m.id}')"><i class="fas fa-map-marker-alt"></i></button>
                        <button class="btn-icon" title="Delete" onclick="window.dashboard.deleteMission('${m.id}')"><i class="fas fa-trash-alt"></i></button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            console.error('Failed to load mission history:', e);
            container.innerHTML = '<div class="loading-state">Failed to load archive.</div>';
        }
    }

    async focusMission(missionId) {
        this.switchView('dashboard');
        try {
            const resp = await fetch(`/api/detections/${missionId}`);
            const detections = await resp.json();
            // Cache detections for heatmap
            const missionData = this.allMissionsData?.find(m => m.id === missionId);
            if (missionData) missionData.detections = detections;

            if (detections.length > 0) {
                this.renderObservationMarkers(detections);
                const lats = detections.map(d => d.lat);
                const lons = detections.map(d => d.lon);
                const bounds = [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
                this.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
                this.showToast(`Loaded ${detections.length} detections from mission.`, 'success');
            } else {
                this.showToast('Mission has no detections.', 'warning');
            }
        } catch (e) {
            this.showToast('Failed to load mission data.', 'error');
        }
    }

    async deleteMission(missionId) {
        if (!confirm('Delete this mission and all its detections?')) return;
        try {
            const resp = await fetch(`/api/missions/${missionId}`, { method: 'DELETE' });
            if (resp.ok) {
                this.showToast('Mission deleted.', 'success');
                this.renderMissionHistory();
                this.fetchSites();
            } else {
                this.showToast('Failed to delete mission.', 'error');
            }
        } catch (e) {
            this.showToast('Network error deleting mission.', 'error');
        }
    }

    exportDetection(missionId, detectionId, format) {
        // Fetch mission detections and filter for this one
        fetch(`/api/detections/${missionId}`)
            .then(r => r.json())
            .then(detections => {
                const d = detections.find(x => x.id === detectionId);
                if (!d) { this.showToast('Detection not found.', 'error'); return; }
                if (format === 'csv') {
                    const headers = ['id','lat','lon','timestamp','speed_kmh','heading','heading_desc','confidence','s_score'];
                    const values = headers.map(h => {
                        const v = d[h];
                        return typeof v === 'string' && v.includes(',') ? `"${v}"` : v;
                    });
                    const csv = [headers.join(','), values.join(',')].join('\n');
                    const blob = new Blob([csv], { type: 'text/csv' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `detection_${detectionId}.csv`;
                    a.click();
                    URL.revokeObjectURL(url);
                    this.showToast('CSV exported.', 'success');
                } else if (format === 'geojson') {
                    const feature = {
                        type: 'Feature',
                        geometry: { type: 'Point', coordinates: [d.lon, d.lat] },
                        properties: { ...d }
                    };
                    delete feature.properties._feature_signature;
                    const geojson = { type: 'FeatureCollection', features: [feature] };
                    const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/geo+json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `detection_${detectionId}.geojson`;
                    a.click();
                    URL.revokeObjectURL(url);
                    this.showToast('GeoJSON exported.', 'success');
                }
            })
            .catch(() => this.showToast('Export failed.', 'error'));
    }

    checkStoredCredentials() {
        const id = localStorage.getItem('drishx_copernicus_id');
        const secret = localStorage.getItem('drishx_copernicus_secret');

        if (id && secret) {
            console.log("DrishX: Stored tactical credentials found. Establishing link...");
            const idInput = document.getElementById('copernicus-id');
            const secretInput = document.getElementById('copernicus-secret');
            if (idInput) idInput.value = id;
            if (secretInput) secretInput.value = secret;
            this.handleAuthSave(true); // silent = true
        }
    }

    async handleAuthSave(silent = false) {
        const idInput = document.getElementById('copernicus-id');
        const secretInput = document.getElementById('copernicus-secret');
        const statusEl = document.getElementById('auth-status');
        const connectBtn = document.getElementById('save-auth');

        if (!idInput || !secretInput) return;

        const id = idInput.value.trim();
        const secret = secretInput.value.trim();

        if (!id || !secret) {
            if (!silent) this.notify("Credentials required for orbital link.", "error");
            return;
        }

        if (!silent) {
            statusEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Establishing Orbital Link...';
            statusEl.className = 'portal-status-msg text-muted';
            if (connectBtn) {
                connectBtn.disabled = true;
                const btnText = connectBtn.querySelector('.btn-text');
                if (btnText) btnText.textContent = 'Linking...';
            }
        }

        try {
            const res = await fetch('/api/auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ client_id: id, client_secret: secret })
            });
            const data = await res.json();

            if (data.status === 'success') {
                localStorage.setItem('drishx_copernicus_id', id);
                localStorage.setItem('drishx_copernicus_secret', secret);

                if (!silent) {
                    statusEl.innerHTML = '<i class="fas fa-check-circle text-success"></i> Tactical Link Established.';
                    this.notify("DrishX: Copernicus link active.", "success");
                }
            } else {
                if (!silent) {
                    statusEl.innerHTML = `<i class="fas fa-exclamation-triangle text-error"></i> ${data.message}`;
                    this.notify("Orbital Handshake Failed.", "error");
                }
            }
        } catch (err) {
            if (!silent) {
                statusEl.innerHTML = '<i class="fas fa-times-circle text-error"></i> Terminal error during link.';
                console.error(err);
            }
        } finally {
            if (connectBtn) {
                connectBtn.disabled = false;
                const btnText = connectBtn.querySelector('.btn-text');
                if (btnText) btnText.textContent = 'Establish Orbital Link';
            }
        }
    }
}

window.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new DrishXDashboard();
});
