// Escape operator-entered strings before they go into innerHTML.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ₹ with Indian lakh grouping, whole rupees: 445875 -> "₹4,45,875".
const inrFormat = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const formatInr = v => inrFormat.format(v);

// FastAPI sends `detail` as a string for our own HTTPExceptions and as an array of
// per-field objects for Pydantic 422s. Flatten both into one readable line.
function apiErrorMessage(payload, fallback) {
    const detail = payload && payload.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail
            .map(d => `${(d.loc || []).slice(1).join('.') || 'field'}: ${d.msg}`)
            .join('; ');
    }
    return fallback;
}

async function request(path, options, fallback) {
    const res = await fetch(path, options);
    // An expired or missing session anywhere means back to the sign-in screen.
    // The /auth/ routes are exempt: a failed login must show its own message.
    if (res.status === 401 && !path.includes('/auth/') && window.app) {
        app.showLogin();
    }
    if (!res.ok) {
        throw new Error(apiErrorMessage(await res.json().catch(() => null), fallback));
    }
    return res.status === 204 ? null : res.json();
}

const jsonBody = data => ({
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
});

// API Interaction Layer
const api = {
    baseUrl: '/api',

    async getProjects(search) {
        const query = search ? `?${new URLSearchParams({ search })}` : '';
        try {
            return await request(`${this.baseUrl}/projects/${query}`, {}, 'Failed to fetch projects');
        } catch (err) {
            console.error(err);
            return [];
        }
    },

    createProject(data) {
        return request(`${this.baseUrl}/projects/`, { method: 'POST', ...jsonBody(data) }, 'Validation Error');
    },

    updateProject(id, data) {
        return request(`${this.baseUrl}/projects/${id}`, { method: 'PUT', ...jsonBody(data) }, 'Validation Error');
    },

    deleteProject(id) {
        return request(`${this.baseUrl}/projects/${id}`, { method: 'DELETE' }, 'Could not delete proposal');
    },

    calculateProject(id) {
        // Surfaces e.g. "PVGIS rejected the site location: Location over the sea".
        return request(`${this.baseUrl}/projects/${id}/calculate`, { method: 'POST' }, 'Calculation failed');
    },

    login(email, password) {
        return request(`${this.baseUrl}/auth/login`, { method: 'POST', ...jsonBody({ email, password }) },
            'Sign in failed');
    },

    logout() {
        return request(`${this.baseUrl}/auth/logout`, { method: 'POST' }, 'Sign out failed');
    },

    me() {
        return request(`${this.baseUrl}/auth/me`, {}, 'Not signed in');
    },

    getPanels() {
        return request(`${this.baseUrl}/catalog/panels`, {}, 'Could not load the panel catalog');
    },

    getInverters() {
        return request(`${this.baseUrl}/catalog/inverters`, {}, 'Could not load the inverter catalog');
    },

    getBuildingFootprint(latitude, longitude) {
        const params = new URLSearchParams({ latitude, longitude });
        return request(`${this.baseUrl}/geospatial/building?${params}`, {}, 'OpenStreetMap building data unavailable');
    }
};
