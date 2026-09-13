const app = {
    currentProjectId: null,
    currentProject: null,

    init() {
        this.loadDashboard();
    },

    showView(viewId) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active', 'hidden'));
        document.querySelectorAll('.view').forEach(v => {
            if (v.id === viewId) v.classList.add('active');
            else v.classList.add('hidden');
        });

        if (viewId === 'dashboard-view') {
            this.loadDashboard();
        }
    },

    async loadDashboard() {
        const grid = document.getElementById('projects-grid');
        grid.innerHTML = '<div class="loading">Loading projects...</div>';

        const projects = await api.getProjects();
        grid.innerHTML = '';

        if (projects.length === 0) {
            grid.innerHTML = '<p class="text-gray" style="grid-column: 1/-1">No proposals found. Create one!</p>';
            return;
        }

        projects.forEach(p => {
            const card = document.createElement('div');
            card.className = 'card project-card';
            card.innerHTML = `
                <h3>${p.project_name}</h3>
                <p><strong>Client:</strong> ${p.client_name}</p>
                <p><strong>System:</strong> ${p.capacity_kwp || '?'} kWp</p>
                <p><strong>Date:</strong> ${new Date(p.created_at).toLocaleDateString()}</p>
            `;
            card.onclick = () => this.viewProjectReport(p);
            grid.appendChild(card);
        });
    },

    async handleFormSubmit(e) {
        e.preventDefault();
        const btn = document.getElementById('btnSubmitForm');
        const errSpan = document.getElementById('formError');
        btn.disabled = true;
        btn.textContent = 'Generating...';
        errSpan.textContent = '';

        try {
            // Gather form data
            const data = {
                project_name: document.getElementById('project_name').value,
                client_name: document.getElementById('client_name').value,
                site_address: document.getElementById('site_address').value,
                latitude: parseFloat(document.getElementById('latitude').value),
                longitude: parseFloat(document.getElementById('longitude').value),
                date: document.getElementById('date').value,

                num_panels: parseInt(document.getElementById('num_panels').value),
                panel_wattage: parseFloat(document.getElementById('panel_wattage').value),
                panel_model: document.getElementById('panel_model').value,
                inverter_model: document.getElementById('inverter_model').value,
                roof_area_sqm: parseFloat(document.getElementById('roof_area_sqm').value),
                degradation_rate: parseFloat(document.getElementById('degradation_rate').value),

                temp_loss_pct: parseFloat(document.getElementById('temp_loss_pct').value),
                shading_loss_pct: parseFloat(document.getElementById('shading_loss_pct').value),
                soiling_loss_pct: parseFloat(document.getElementById('soiling_loss_pct').value),
                inverter_loss_pct: parseFloat(document.getElementById('inverter_loss_pct').value),
                mismatch_loss_pct: parseFloat(document.getElementById('mismatch_loss_pct').value),
                dc_wiring_loss_pct: parseFloat(document.getElementById('dc_wiring_loss_pct').value),
                ac_wiring_loss_pct: parseFloat(document.getElementById('ac_wiring_loss_pct').value),
            };

            // 1. Create project
            const project = await api.createProject(data);

            // 2. Run calculations
            const calculatedProject = await api.calculateProject(project.id);

            // 3. Show report
            this.renderReport(calculatedProject);
            this.showView('report-view');

        } catch (error) {
            errSpan.textContent = error.message;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Generate Report';
        }
    },

    async viewProjectReport(project) {
        if (!project.is_calculated) {
            project = await api.calculateProject(project.id);
        }
        this.renderReport(project);
        this.showView('report-view');
    },

    renderReport(p) {
        this.currentProjectId = p.id;
        this.currentProject = p;

        // System Summary
        document.getElementById('r_capacity').innerHTML = `${p.capacity_kwp} <span class="unit">kWp</span>`;
        document.getElementById('r_panels').textContent = p.num_panels;
        document.getElementById('r_panel_w').textContent = `${p.panel_wattage}W`;
        document.getElementById('r_roof_area').innerHTML = `${p.roof_area_sqm} <span class="unit">m²</span>`;

        // Generation
        const mwh = (p.annual_gen_kwh / 1000).toFixed(1);
        document.getElementById('r_annual_mwh').textContent = `${mwh} MWh`;
        document.getElementById('r_specific_yield').textContent = `${p.specific_yield} kWh/kWp`;
        document.getElementById('r_pr').textContent = `${p.performance_ratio.toFixed(1)}%`;

        // Chart
        if (p.monthly_gen_json) {
            chartManager.renderMonthlyChart('monthlyChart', p.monthly_gen_json);
        }

        // Losses
        const lossContainer = document.getElementById('r_losses');
        lossContainer.innerHTML = '';

        const lossItems = [
            { name: 'Temperature', val: p.temp_loss_pct, color: 'var(--loss-temp)' },
            { name: 'Shading', val: p.shading_loss_pct, color: 'var(--bg-color)' }, // invisible if 0
            { name: 'Soiling', val: p.soiling_loss_pct, color: 'var(--loss-soil)' },
            { name: 'Inverter', val: p.inverter_loss_pct, color: 'var(--loss-inv)' },
            { name: 'Mismatch', val: p.mismatch_loss_pct, color: 'var(--loss-mism)' },
            { name: 'DC Wiring', val: p.dc_wiring_loss_pct, color: 'var(--loss-dc)' },
            { name: 'AC Wiring', val: p.ac_wiring_loss_pct, color: 'var(--bg-color)' }
        ];

        lossItems.forEach(item => {
            // scale visually: max is around 12% in the UI, so width = val * 3 % aprox
            const width = Math.min(item.val * 3, 100);
            const html = `
                <div class="loss-row">
                    <div class="loss-name">${item.name}</div>
                    <div class="loss-bar-container">
                        <div class="loss-bar" style="width: ${width}%; background-color: ${item.val > 0 ? item.color : 'transparent'}"></div>
                    </div>
                    <div class="loss-value">${item.val.toFixed(1)}%</div>
                </div>
            `;
            lossContainer.innerHTML += html;
        });

        lossContainer.innerHTML += `
            <div class="loss-total-row">
                <span>Total System Loss</span>
                <span>${p.total_system_loss.toFixed(1)}%</span>
            </div>
        `;

        // Projection
        document.getElementById('r_lifetime').textContent = `${p.lifetime_gen_mwh.toFixed(1)} MWh`;
        document.getElementById('r_year25').textContent = `${p.year25_output_mwh.toFixed(1)} MWh`;

        const year25Ratio = Math.round((p.year25_output_mwh / mwh) * 100);
        document.getElementById('r_degradation_pct').textContent = `(${year25Ratio}% of Year 1)`;
    },

    downloadPdf() {
        if (!this.currentProjectId) return;

        // Direct browser download
        const url = `/api/projects/${this.currentProjectId}/report/pdf`;
        window.open(url, '_blank');
    }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    app.init();
});
