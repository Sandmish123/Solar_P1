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
        if (!res.ok) throw new Error('Calculation failed');
        return await res.json();
    },

    async getBuildingFootprint(latitude, longitude) {
        const params = new URLSearchParams({ latitude, longitude });
        const res = await fetch(`${this.baseUrl}/geospatial/building?${params}`);
        if (!res.ok) throw new Error('OpenStreetMap building data unavailable');
        return await res.json();
    }
};
