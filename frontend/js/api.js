// Escape operator-entered strings before they go into innerHTML.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ₹ with Indian lakh grouping, whole rupees: 445875 -> "₹4,45,875".
const inrFormat = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const formatInr = v => inrFormat.format(v);

// API Interaction Layer
const api = {
    baseUrl: '/api',

    async getProjects() {
        try {
            const res = await fetch(`${this.baseUrl}/projects/`);
            if (!res.ok) throw new Error('Failed to fetch projects');
            return await res.json();
        } catch (err) {
            console.error(err);
            return [];
        }
    },

    async createProject(data) {
        const res = await fetch(`${this.baseUrl}/projects/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Validation Error');
        }
        return await res.json();
    },

    async calculateProject(id) {
        const res = await fetch(`${this.baseUrl}/projects/${id}/calculate`, {
            method: 'POST'
        });
        if (!res.ok) {
            // Surface e.g. "PVGIS rejected the site location: Location over the sea".
            const err = await res.json().catch(() => ({}));
            throw new Error(typeof err.detail === 'string' ? err.detail : 'Calculation failed');
        }
        return await res.json();
    },

    async getBuildingFootprint(latitude, longitude) {
        const params = new URLSearchParams({ latitude, longitude });
        const res = await fetch(`${this.baseUrl}/geospatial/building?${params}`);
        if (!res.ok) throw new Error('OpenStreetMap building data unavailable');
        return await res.json();
    }
};
