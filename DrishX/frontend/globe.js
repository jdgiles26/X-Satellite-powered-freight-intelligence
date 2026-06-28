/**
 * GlobeView — 3D Orbital Visualization for ARGUS
 * Powered by Globe.gl
 */
class GlobeView {
    constructor(containerId) {
        this.containerId = containerId;
        this.globe = null;
        this.animationId = null;
        this.isHovered = false;
        this.detections = [];
        this.feeds = [];
        this.corridors = [];
        this.layers = {
            detections: true,
            feeds: true,
            corridors: true
        };
    }

    init() {
        const container = document.getElementById(this.containerId);
        if (!container) {
            console.error('Globe container not found:', this.containerId);
            return;
        }

        this.globe = GlobeGL()
            (container)
            .backgroundColor('#05080b')
            .globeImageUrl('//unpkg.com/three-globe/example/img/earth-dark.jpg')
            .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
            .atmosphereColor('#00f2ff')
            .atmosphereAltitude(0.15)
            .showAtmosphere(true);

        // Initial camera position
        this.globe.pointOfView({ lat: 30, lng: 10, altitude: 2.5 });

        // Hover handling to pause rotation
        const renderer = this.globe.renderer();
        const canvas = renderer.domElement;
        canvas.addEventListener('mouseenter', () => { this.isHovered = true; });
        canvas.addEventListener('mouseleave', () => { this.isHovered = false; });

        this.animate();
        this.resize();
    }

    renderDetections(detections) {
        this.detections = detections || [];
        if (!this.globe) return;

        if (!this.layers.detections || this.detections.length === 0) {
            this.globe.pointsData([]);
            return;
        }

        const points = this.detections.map(d => ({
            lat: d.lat,
            lng: d.lon,
            alt: (d.confidence || 0.5) * 0.3,
            radius: 0.4 + (d.confidence || 0.5) * 0.4,
            color: '#00f2ff'
        }));

        this.globe
            .pointsData(points)
            .pointAltitude('alt')
            .pointRadius('radius')
            .pointColor('color')
            .pointResolution(12);
    }

    renderFeeds(feeds) {
        this.feeds = feeds || [];
        if (!this.globe) return;

        if (!this.layers.feeds || this.feeds.length === 0) {
            this.globe.hexBinPointsData([]);
            return;
        }

        const severityColors = {
            CRITICAL: '#dc2626',
            HIGH: '#ef4444',
            MEDIUM: '#f59e0b',
            LOW: '#10b981'
        };

        const points = this.feeds.map(f => ({
            lat: f.lat,
            lng: f.lon,
            color: severityColors[f.severity] || '#10b981',
            radius: 0.5
        }));

        this.globe
            .hexBinPointsData(points)
            .hexBinPointWeight('radius')
            .hexBinResolution(3)
            .hexBinMerge(true)
            .hexBinColor(d => d.points?.[0]?.color || '#10b981')
            .hexBinAltitude(d => Math.sqrt(d.sumWeight) * 0.02);
    }

    renderCorridors(corridors) {
        this.corridors = corridors || [];
        if (!this.globe) return;

        if (!this.layers.corridors || this.corridors.length === 0) {
            this.globe.arcsData([]);
            return;
        }

        const arcs = this.corridors.map(c => ({
            startLat: c.start_lat,
            startLng: c.start_lng,
            endLat: c.end_lat,
            endLng: c.end_lng,
            color: '#00ff9d'
        }));

        this.globe
            .arcsData(arcs)
            .arcColor('color')
            .arcDashLength(0.5)
            .arcDashGap(0.2)
            .arcDashAnimateTime(2000)
            .arcStroke(0.8)
            .arcAltitudeAutoScale(0.3);
    }

    animate() {
        if (!this.globe) return;

        if (!this.isHovered) {
            const pov = this.globe.pointOfView();
            this.globe.pointOfView({
                lat: pov.lat,
                lng: pov.lng + 0.1,
                altitude: pov.altitude
            });
        }

        this.animationId = requestAnimationFrame(() => this.animate());
    }

    resize() {
        if (!this.globe) return;
        const container = document.getElementById(this.containerId);
        if (container) {
            const width = container.clientWidth;
            const height = container.clientHeight;
            this.globe.width(width).height(height);
        }
    }

    toggleLayer(layer) {
        if (this.layers.hasOwnProperty(layer)) {
            this.layers[layer] = !this.layers[layer];
            // Refresh current data
            this.renderDetections(this.detections);
            this.renderFeeds(this.feeds);
            this.renderCorridors(this.corridors);
        }
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        if (this.globe) {
            const container = document.getElementById(this.containerId);
            if (container) container.innerHTML = '';
            this.globe = null;
        }
    }
}
