const mapManager = {
    map: null,
    currentProjectData: null,
    solarMarker: null,
    footprint: null,
    interactionsBound: false,
    activeSeason: 'summer',
    mapMode: 'satellite',
    seasons: {
        winter: { month: 11, day: 21 },
        summer: { month: 5, day: 21 },
        equinox: { month: 2, day: 20 },
        today: null
    },

    open3DView() {
        if (!app.currentProjectId) return;

        // Hide report view, show 3D Model view
        app.showView('model3d-view');
        this.bindInteractions();

        // Use current data dynamically if available, otherwise fetch
        this.fetchAndRenderMap(app.currentProjectId);
    },

    async fetchAndRenderMap(projectId) {
        const project = app.currentProject && app.currentProject.id === projectId
            ? app.currentProject
            : await api.getProjects().then(projs => projs.find(p => p.id === projectId));
        if (!project) return;

        this.currentProjectData = project;
        this.renderProjectDetails(project);

        const lng = project.longitude || 77.061796;
        const lat = project.latitude || 28.507563;

        this.initMap(lng, lat);
        this.renderSolarModel(project);
        this.setSeason(this.activeSeason);
        await this.loadBuildingFootprint(lat, lng);
    },

    bindInteractions() {
        if (this.interactionsBound) return;
        this.interactionsBound = true;

        document.querySelectorAll('.season-btn').forEach(button => {
            button.addEventListener('click', () => this.setSeason(button.dataset.season));
        });
        document.getElementById('sun-time').addEventListener('input', event => {
            this.updateSunTime(Number(event.target.value));
        });
        document.querySelectorAll('.tool-btn').forEach(button => {
            button.addEventListener('click', () => this.activateTool(button.dataset.tool));
        });
        document.getElementById('model-pitch').addEventListener('input', event => {
            this.updateCamera({ pitch: Number(event.target.value) });
        });
        document.getElementById('model-zoom').addEventListener('input', event => {
            this.updateCamera({ zoom: Number(event.target.value) });
        });
        document.querySelector('.model-reset').addEventListener('click', () => {
            document.getElementById('model-pitch').value = 60;
            document.getElementById('model-zoom').value = 19;
            this.updateCamera({ pitch: 60, zoom: 19 });
        });
    },

    setSeason(season) {
        const project = this.currentProjectData || {};
        const config = this.calculateSolarDay(season, Number(project.latitude) || 28.5, Number(project.longitude) || 77.1);
        this.activeSeason = season;
        document.querySelectorAll('.season-btn').forEach(button => {
            button.classList.toggle('active', button.dataset.season === season);
        });
        document.getElementById('sun-time').value = config.position;
        document.getElementById('m_sunrise').textContent = `Sunrise: ${this.formatTime(config.sunrise)}`;
        document.getElementById('m_sunset').textContent = `Sunset: ${this.formatTime(config.sunset)}`;
        this.updateSunTime(config.position);
    },

    updateSunTime(position) {
        const project = this.currentProjectData || {};
        const config = this.calculateSolarDay(this.activeSeason, Number(project.latitude) || 28.5, Number(project.longitude) || 77.1);
        const daylightMinutes = config.sunset - config.sunrise;
        const minutes = config.sunrise + daylightMinutes * position / 100;
        const solar = this.solarPosition(config.date, minutes, Number(project.latitude) || 28.5, Number(project.longitude) || 77.1);
        document.getElementById('m_sun_time').textContent = this.formatTime(minutes);
        document.getElementById('model3d-view').classList.toggle('model3d-night', solar.elevation < 0);
        const sunOrb = document.getElementById('sun-orb');
        if (sunOrb) {
            const arcProgress = position / 100;
            const x = 12 + arcProgress * 76;
            // Keep the same sky scale for every season so lower winter sun is visible.
            const y = 76 - Math.max(0, solar.elevation) / 90 * 62;
            sunOrb.style.left = `${x}%`;
            sunOrb.style.top = `${y}%`;
            sunOrb.title = `${this.formatTime(minutes)} · ${Math.round(Math.max(0, solar.elevation))}° elevation · ${Math.round(solar.azimuth)}° azimuth`;
        }
        if (this.map && typeof this.map.setLight === 'function' && this.map.isStyleLoaded()) {
            const daylight = solar.elevation > 0;
            this.map.setLight({
                anchor: 'viewport',
                color: daylight ? '#fff4d6' : '#94a3c7',
                intensity: daylight ? Math.max(0.35, Math.min(0.9, solar.elevation / 65)) : 0.22
            });
        }
    },

    calculateSolarDay(season, latitude, longitude) {
        const now = new Date();
        const selected = this.seasons[season];
        const date = selected
            ? new Date(now.getFullYear(), selected.month, selected.day)
            : now;
        const dayOfYear = Math.floor((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) -
            Date.UTC(date.getFullYear(), 0, 0)) / 86400000);
        const declination = 23.44 * Math.sin((2 * Math.PI / 365) * (dayOfYear - 81) / 1);
        const latitudeRadians = latitude * Math.PI / 180;
        const declinationRadians = declination * Math.PI / 180;
        const cosineHourAngle = (Math.cos(90.833 * Math.PI / 180) /
            (Math.cos(latitudeRadians) * Math.cos(declinationRadians)) -
            Math.tan(latitudeRadians) * Math.tan(declinationRadians));
        const hourAngle = Math.acos(Math.max(-1, Math.min(1, cosineHourAngle))) * 180 / Math.PI;
        const equationOfTime = 9.87 * Math.sin(2 * (2 * Math.PI * (dayOfYear - 81) / 364)) -
            7.53 * Math.cos(2 * Math.PI * (dayOfYear - 81) / 364) -
            1.5 * Math.sin(2 * Math.PI * (dayOfYear - 81) / 364);
        const timezoneOffset = this.getTimezoneOffset(longitude);
        const solarNoon = 720 - 4 * longitude - equationOfTime + timezoneOffset * 60;
        const sunrise = solarNoon - hourAngle * 4;
        const sunset = solarNoon + hourAngle * 4;
        const maxElevation = 90 - Math.abs(latitude - declination);
        return {
            date,
            sunrise,
            sunset,
            maxElevation,
            position: 50
        };
    },

    solarPosition(date, minutes, latitude, longitude) {
        const dayOfYear = Math.floor((Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) -
            Date.UTC(date.getFullYear(), 0, 0)) / 86400000);
        const declination = 23.44 * Math.sin((2 * Math.PI / 365) * (dayOfYear - 81));
        const equationOfTime = 9.87 * Math.sin(2 * (2 * Math.PI * (dayOfYear - 81) / 364)) -
            7.53 * Math.cos(2 * Math.PI * (dayOfYear - 81) / 364) -
            1.5 * Math.sin(2 * Math.PI * (dayOfYear - 81) / 364);
        const timezoneOffset = this.getTimezoneOffset(longitude);
        const solarMinutes = minutes + equationOfTime + 4 * longitude - timezoneOffset * 60;
        const hourAngle = (solarMinutes - 720) / 4;
        const latitudeRadians = latitude * Math.PI / 180;
        const declinationRadians = declination * Math.PI / 180;
        const hourAngleRadians = hourAngle * Math.PI / 180;
        const elevation = Math.asin(
            Math.sin(latitudeRadians) * Math.sin(declinationRadians) +
            Math.cos(latitudeRadians) * Math.cos(declinationRadians) * Math.cos(hourAngleRadians)
        ) * 180 / Math.PI;
        const azimuth = (Math.atan2(
            Math.sin(hourAngleRadians),
            Math.cos(hourAngleRadians) * Math.sin(latitudeRadians) -
            Math.tan(declinationRadians) * Math.cos(latitudeRadians)
        ) * 180 / Math.PI + 180 + 360) % 360;
        return { elevation, azimuth };
    },

    getTimezoneOffset(longitude) {
        // The proposals are in India; preserve its UTC+05:30 civil time.
        if (longitude >= 60 && longitude <= 100) return 5.5;
        return Math.round(longitude / 15 * 2) / 2;
    },

    formatTime(totalMinutes) {
        const roundedMinutes = Math.round(totalMinutes);
        const hours = Math.floor(roundedMinutes / 60) % 24;
        const minutes = (roundedMinutes % 60).toString().padStart(2, '0');
        const suffix = hours >= 12 ? 'PM' : 'AM';
        const displayHour = hours % 12 || 12;
        return `${displayHour}:${minutes} ${suffix}`;
    },

    activateTool(tool) {
        document.querySelectorAll('.tool-btn').forEach(button => {
            button.classList.toggle('active', button.dataset.tool === tool);
        });
        const metrics = document.querySelector('.model-metrics-panel');
        const settings = document.getElementById('model-settings');
        const marker = document.getElementById('solar-model-marker');

        if (tool === 'report') {
            metrics.hidden = !metrics.hidden;
            settings.hidden = true;
        } else if (tool === 'settings') {
            settings.hidden = !settings.hidden;
        } else if (tool === 'array') {
            marker.hidden = false;
            metrics.hidden = false;
            settings.hidden = true;
        } else if (tool === 'map') {
            settings.hidden = true;
            this.toggleMapMode();
        }
    },

    toggleMapMode() {
        this.mapMode = this.mapMode === 'satellite' ? 'street' : 'satellite';
        const mapElement = document.getElementById('map');
        mapElement.classList.toggle('map-street-mode', this.mapMode === 'street');
        if (this.map) {
            if (this.map.getLayer('esri-satellite')) {
                this.map.setLayoutProperty(
                    'esri-satellite',
                    'visibility',
                    this.mapMode === 'satellite' ? 'visible' : 'none'
                );
            }
        }
    },

    updateCamera(options) {
        if (this.map) this.map.easeTo({ ...options, duration: 350 });
    },

    renderProjectDetails(project) {
        const values = {
            m_project_name: project.project_name,
            m_client_name: project.client_name,
            m_capacity: project.capacity_kwp,
            m_panels: project.num_panels,
            m_panel_wattage: project.panel_wattage,
            m_roof_area: project.roof_area_sqm,
            m_panel_model: project.panel_model,
            m_inverter_model: project.inverter_model,
            m_site_address: project.site_address,
            m_date: project.date,
            m_degradation_rate: `${Number(project.degradation_rate || 0).toFixed(1)}% / year`,
            m_annual_generation: `${((project.annual_gen_kwh || 0) / 1000).toFixed(1)} MWh`,
            m_specific_yield: `${(project.specific_yield || 0).toFixed(0)} kWh/kWp`,
            m_performance_ratio: `${(project.performance_ratio || 0).toFixed(1)}%`,
            m_total_loss: `${(project.total_system_loss || 0).toFixed(1)}%`,
            m_lifetime_generation: `${(project.lifetime_gen_mwh || 0).toFixed(1)} MWh`,
            m_year25_output: `${(project.year25_output_mwh || 0).toFixed(1)} MWh`
        };

        Object.entries(values).forEach(([id, value]) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value == null ? '-' : value;
        });

        const losses = [
            ['Temperature', project.temp_loss_pct],
            ['Shading', project.shading_loss_pct],
            ['Soiling', project.soiling_loss_pct],
            ['Inverter', project.inverter_loss_pct],
            ['Mismatch', project.mismatch_loss_pct],
            ['DC wiring', project.dc_wiring_loss_pct],
            ['AC wiring', project.ac_wiring_loss_pct]
        ];
        document.getElementById('m_loss_breakdown').innerHTML = losses
            .map(([name, value]) => `<div><span>${name}</span><strong>${Number(value || 0).toFixed(1)}%</strong></div>`)
            .join('');
    },

    async loadBuildingFootprint(latitude, longitude) {
        const sourceElement = document.getElementById('m_geometry_source');
        try {
            const footprint = await api.getBuildingFootprint(latitude, longitude);
            this.footprint = footprint;
            sourceElement.textContent = footprint.found
                ? (footprint.estimated ? 'OpenStreetMap (height estimated)' : 'OpenStreetMap (height tagged)')
                : 'Estimated from proposal roof area';
            this.renderBuildingFootprint(footprint);
        } catch (error) {
            const fallback = this.createEstimatedFootprint(latitude, longitude);
            this.footprint = fallback;
            sourceElement.textContent = 'OSM unavailable (estimated)';
            this.renderBuildingFootprint(fallback);
            console.warn(error.message);
        }
    },

    createEstimatedFootprint(latitude, longitude) {
        return {
            found: false,
            source: 'Estimated',
            estimated: true,
            height_m: 3,
            geometry: {
                type: 'Polygon',
                coordinates: [[
                    [longitude - 0.00012, latitude - 0.00008],
                    [longitude + 0.00012, latitude - 0.00008],
                    [longitude + 0.00012, latitude + 0.00008],
                    [longitude - 0.00012, latitude + 0.00008],
                    [longitude - 0.00012, latitude - 0.00008]
                ]]
            }
        };
    },

    renderBuildingFootprint(footprint) {
        if (!this.map || !footprint || !footprint.geometry || !this.map.isStyleLoaded()) return;
        const sourceId = 'proposal-building-footprint';
        if (this.map.getLayer('proposal-building-extrusion')) this.map.removeLayer('proposal-building-extrusion');
        if (this.map.getSource(sourceId)) this.map.removeSource(sourceId);
        this.map.addSource(sourceId, {
            type: 'geojson',
            data: {
                type: 'Feature',
                properties: { height: footprint.height_m || 3 },
                geometry: footprint.geometry
            }
        });
        this.map.addLayer({
            id: 'proposal-building-extrusion',
            type: 'fill-extrusion',
            source: sourceId,
            paint: {
                'fill-extrusion-color': '#c9d1d9',
                'fill-extrusion-height': ['get', 'height'],
                'fill-extrusion-base': 0,
                'fill-extrusion-opacity': 0.82
            }
        });
    },

    renderSolarModel(project) {
        const markerElement = document.getElementById('solar-model-marker');
        if (!markerElement) return;

        const panelCount = Math.max(1, Number(project.num_panels) || 1);
        const columns = Math.min(10, Math.ceil(Math.sqrt(panelCount)));
        const rows = Math.ceil(panelCount / columns);
        const modelScale = Math.min(1.35, Math.max(1, Math.sqrt(panelCount / 60)));
        const panels = Array.from({ length: panelCount }, (_, index) =>
            `<span class="solar-panel" data-panel-index="${index + 1}" title="Panel ${index + 1}"></span>`
        ).join('');
        markerElement.innerHTML = `
            <div class="solar-model" style="--panel-columns:${columns}; --panel-rows:${rows}; --model-scale:${modelScale}">
                <div class="solar-roof">
                    <div class="solar-panels">${panels}</div>
                </div>
                <div class="solar-building-front"></div>
                <div class="solar-building-side"></div>
                <div class="solar-model-label">${panelCount} panels</div>
            </div>
        `;
        markerElement.querySelectorAll('.solar-panel').forEach(panel => {
            panel.addEventListener('click', event => {
                event.stopPropagation();
                this.selectPanel(Number(panel.dataset.panelIndex));
            });
        });

        if (this.map && project.longitude && project.latitude) {
            if (this.solarMarker) this.solarMarker.remove();
            this.solarMarker = new maplibregl.Marker({ element: markerElement, anchor: 'center' })
                .setLngLat([project.longitude, project.latitude])
                .addTo(this.map);
        }
    },

    selectPanel(panelNumber) {
        document.querySelectorAll('.solar-panel').forEach(panel => {
            panel.classList.toggle('selected', Number(panel.dataset.panelIndex) === panelNumber);
        });
        const selection = document.getElementById('model-selection');
        selection.hidden = false;
        document.getElementById('m_selected_panel').textContent = `Panel ${panelNumber}`;
        document.getElementById('m_selected_panel_detail').textContent = `${this.currentProjectData.panel_wattage} W ${this.currentProjectData.panel_model}`;
    },

    enableMapFallback() {
        document.getElementById('map').classList.add('map-fallback');
    },

    initMap(lng, lat) {
        if (this.map) {
            // Already initialized, just fly to it
            this.map.flyTo({ center: [lng, lat], zoom: 20, pitch: 55, bearing: -15 });
            this.map.resize();
            if (this.solarMarker) this.solarMarker.setLngLat([lng, lat]);
            return;
        }

        // Create new map
        this.map = new maplibregl.Map({
            container: 'map',
            style: 'https://tiles.openfreemap.org/styles/liberty',
            center: [lng, lat],
            zoom: 20,
            pitch: 55,
            bearing: -15, // A slight angle for 3D effect
            antialias: true
        });
        this.map.on('error', () => this.enableMapFallback());

        this.map.on('style.load', () => {
            this.addSatelliteImagery();
            this.renderBuildingFootprint(this.footprint);
            this.renderSolarModel(this.currentProjectData);
        });
    },

    addSatelliteImagery() {
        if (this.map.getSource('esri-world-imagery')) return;
        this.map.addSource('esri-world-imagery', {
            type: 'raster',
            tiles: [
                'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
            ],
            tileSize: 256,
            attribution: 'Esri, Maxar, Earthstar Geographics'
        });
        this.map.addLayer({
            id: 'esri-satellite',
            type: 'raster',
            source: 'esri-world-imagery',
            paint: { 'raster-opacity': 0.86 }
        }, this.map.getStyle().layers.find(layer => layer.type === 'symbol')?.id);
    }
};
