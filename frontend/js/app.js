// Every form field, by input id and how to read it. One list so collecting,
// filling and resetting the form can't drift apart.
const FORM_FIELDS = [
    ['project_name', 'text'],
    ['client_name', 'text'],
    ['site_address', 'text'],
    ['date', 'text'],
    ['latitude', 'number'],
    ['longitude', 'number'],

    ['num_panels', 'int'],
    ['panel_wattage', 'number'],
    ['panel_model', 'text'],
    ['panel_model_id', 'number'],
    ['inverter_model_id', 'number'],
    ['inverter_model', 'text'],
    ['roof_area_sqm', 'number'],
    ['degradation_rate', 'number'],
    ['tilt_deg', 'number'],
    ['azimuth_deg', 'number'],
    ['irradiance_calibration', 'number'],

    ['temp_loss_pct', 'number'],
    ['shading_loss_pct', 'number'],
    ['shading_auto', 'bool'],
    ['soiling_loss_pct', 'number'],
    ['inverter_loss_pct', 'number'],
    ['mismatch_loss_pct', 'number'],
    ['dc_wiring_loss_pct', 'number'],
    ['ac_wiring_loss_pct', 'number'],

    ['system_cost_inr', 'number'],
    ['subsidy_inr', 'number'],
    ['tariff_inr_per_kwh', 'number'],
    ['tariff_escalation_pct', 'number'],
    ['export_ratio_pct', 'number'],
    ['export_tariff_inr_per_kwh', 'number'],
    ['om_cost_pct', 'number'],
    ['discount_rate_pct', 'number'],
    ['inverter_replacement_year', 'int'],
    ['inverter_replacement_cost_inr', 'number'],
];

const app = {
    user: null,
    catalog: { panels: [], inverters: [] },
    currentProjectId: null,
    currentProject: null,
    editingId: null,
    searchTimer: null,

    init() {
        const form = document.getElementById('project-form');
        // Native constraint validation can't focus a field inside a closed <details>,
        // so open the section holding the first invalid input. Capture phase: the
        // `invalid` event does not bubble.
        form.addEventListener('invalid', event => {
            const section = event.target.closest('details');
            if (section) section.open = true;
        }, true);

        this.checkSession();
    },

    // --- session -----------------------------------------------------------

    async checkSession() {
        try {
            this.user = await api.me();
            this.onSignedIn();
        } catch (error) {
            this.showLogin();
        }
    },

    async onSignedIn() {
        document.body.classList.remove('signed-out');
        document.getElementById('user-email').textContent = this.user.email;
        // Loaded once per session: the edit form fills a <select> by value, which
        // only works after its options exist.
        await this.loadCatalog();
        this.showView('dashboard-view');
    },

    async loadCatalog() {
        try {
            const [panels, inverters] = await Promise.all([api.getPanels(), api.getInverters()]);
            this.catalog = { panels, inverters };
        } catch (error) {
            this.catalog = { panels: [], inverters: [] };   // typing the names still works
        }
        this.fillCatalogSelect('panel_model_id', this.catalog.panels,
            p => `${p.manufacturer} ${p.model} — ${p.wp} W`);
        this.fillCatalogSelect('inverter_model_id', this.catalog.inverters,
            i => `${i.manufacturer} ${i.model}${i.ac_kw ? ` — ${i.ac_kw} kW` : ''}`);
    },

    fillCatalogSelect(id, components, label) {
        const select = document.getElementById(id);
        const chosen = select.value;
        select.length = 1;                       // keep the "not from catalog" option
        components.forEach(component => {
            const option = document.createElement('option');
            option.value = component.id;
            option.textContent = label(component);
            select.appendChild(option);
        });
        select.value = chosen;
    },

    onPanelChange() {
        const panel = this.catalog.panels.find(p => String(p.id) === document.getElementById('panel_model_id').value);
        const wattage = document.getElementById('panel_wattage');
        const name = document.getElementById('panel_model');
        if (panel) {
            // The catalog is the source of truth; the server derives wattage from it too.
            name.value = `${panel.manufacturer} ${panel.model}`;
            wattage.value = panel.wp;
        }
        wattage.readOnly = Boolean(panel);
        name.readOnly = Boolean(panel);
    },

    onInverterChange() {
        const inverter = this.catalog.inverters.find(
            i => String(i.id) === document.getElementById('inverter_model_id').value);
        const name = document.getElementById('inverter_model');
        if (inverter) name.value = `${inverter.manufacturer} ${inverter.model}`;
        name.readOnly = Boolean(inverter);
    },

    showLogin() {
        this.user = null;
        this.currentProject = null;
        this.currentProjectId = null;
        document.body.classList.add('signed-out');
        this.showView('login-view');
    },

    async handleLogin(event) {
        event.preventDefault();
        const button = document.getElementById('btnLogin');
        const error = document.getElementById('loginError');
        button.disabled = true;
        error.textContent = '';
        try {
            this.user = await api.login(
                document.getElementById('login_email').value,
                document.getElementById('login_password').value,
            );
            document.getElementById('login-form').reset();
            this.onSignedIn();
        } catch (failure) {
            error.textContent = failure.message;
        } finally {
            button.disabled = false;
        }
    },

    async logout() {
        try {
            await api.logout();
        } finally {
            this.showLogin();
        }
    },

    showView(viewId) {
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active', 'hidden'));
        document.querySelectorAll('.view').forEach(v => {
            if (v.id === viewId) v.classList.add('active');
            else v.classList.add('hidden');
        });

        // Loading the dashboard while signed out would 401 straight back to login.
        if (viewId === 'dashboard-view' && this.user) {
            this.loadDashboard();
        }
    },

    // --- dashboard ---------------------------------------------------------

    onSearchInput() {
        // Debounced: one request per pause, not per keystroke.
        clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(() => this.loadDashboard(), 200);
    },

    async loadDashboard() {
        const grid = document.getElementById('projects-grid');
        const search = document.getElementById('project-search').value.trim();
        grid.innerHTML = '<div class="loading">Loading projects...</div>';

        const projects = await api.getProjects(search);
        grid.innerHTML = '';

        if (projects.length === 0) {
            grid.innerHTML = search
                ? `<p class="text-gray" style="grid-column: 1/-1">No proposals match “${esc(search)}”.</p>`
                : '<p class="text-gray" style="grid-column: 1/-1">No proposals found. Create one!</p>';
            return;
        }

        projects.forEach(p => grid.appendChild(this.projectCard(p)));
    },

    projectCard(p) {
        const card = document.createElement('div');
        card.className = 'card project-card';
        const payback = p.payback_years != null ? `${p.payback_years} yr payback` : '';
        card.innerHTML = `
            <div class="card-top">
                <h3>${esc(p.project_name)}</h3>
                <span class="badge ${p.is_calculated ? 'badge-ok' : 'badge-pending'}">
                    ${p.is_calculated ? 'Calculated' : 'Not calculated'}
                </span>
            </div>
            <p><strong>Client:</strong> ${esc(p.client_name)}</p>
            <p><strong>System:</strong> ${p.capacity_kwp ? `${p.capacity_kwp} kWp` : '—'} ${payback ? `· ${payback}` : ''}</p>
            <p><strong>Created:</strong> ${new Date(p.created_at).toLocaleDateString('en-IN')}</p>
            <div class="card-actions">
                <button type="button" class="btn btn-small btn-primary" data-action="open">Open</button>
                <button type="button" class="btn btn-small btn-secondary" data-action="edit">Edit</button>
                <button type="button" class="btn btn-small btn-danger" data-action="delete">Delete</button>
            </div>
        `;

        const actions = {
            open: () => this.viewProjectReport(p),
            edit: () => this.editProject(p),
            delete: () => this.confirmDelete(p),
        };
        card.querySelectorAll('[data-action]').forEach(button => {
            button.setAttribute('aria-label', `${button.textContent.trim()} ${p.project_name}`);
            button.addEventListener('click', event => {
                event.stopPropagation();
                actions[button.dataset.action]();
            });
        });
        card.addEventListener('click', () => this.viewProjectReport(p));
        return card;
    },

    async confirmDelete(project) {
        if (!confirm(`Delete “${project.project_name}”? This cannot be undone.`)) return;
        try {
            await api.deleteProject(project.id);
            if (this.currentProjectId === project.id) this.currentProjectId = null;
            this.loadDashboard();
        } catch (error) {
            alert(error.message);
        }
    },

    // --- form --------------------------------------------------------------

    collectForm() {
        const data = {};
        FORM_FIELDS.forEach(([id, kind]) => {
            const element = document.getElementById(id);
            if (kind === 'bool') {
                data[id] = element.checked;
                return;
            }
            const raw = element.value;
            if (kind === 'text') {
                data[id] = raw.trim();
            } else if (raw === '') {
                // Blank number: null, not 0. Optional fields mean "auto"; required
                // ones are caught by native validation, or by the API with a
                // field-level message.
                data[id] = null;
            } else {
                data[id] = kind === 'int' ? parseInt(raw, 10) : Number(raw);
            }
        });
        return data;
    },

    fillForm(project) {
        FORM_FIELDS.forEach(([id, kind]) => {
            const element = document.getElementById(id);
            const value = project[id];
            if (kind === 'bool') element.checked = Boolean(value);
            else element.value = value === null || value === undefined ? '' : value;
        });
    },

    setFormMode(heading, submitLabel) {
        document.getElementById('form-heading').textContent = heading;
        document.getElementById('btnSubmitForm').textContent = submitLabel;
        document.getElementById('formError').textContent = '';
    },

    newProject() {
        this.editingId = null;
        // Native reset restores the HTML value attributes, i.e. the engineering
        // defaults, and clears everything else.
        document.getElementById('project-form').reset();
        this.setFormMode('Create Solar Proposal', 'Generate Report');
        this.onPanelChange();
        this.onInverterChange();
        this.showView('form-view');
    },

    editProject(project) {
        this.editingId = project.id;
        this.fillForm(project);
        this.onPanelChange();
        this.onInverterChange();
        this.setFormMode(`Edit: ${project.project_name}`, 'Save & Recalculate');
        this.showView('form-view');
    },

    editCurrent() {
        if (this.currentProject) this.editProject(this.currentProject);
    },

    async handleFormSubmit(e) {
        e.preventDefault();
        const btn = document.getElementById('btnSubmitForm');
        const errSpan = document.getElementById('formError');
        const editing = this.editingId !== null;
        const label = btn.textContent;
        btn.disabled = true;
        btn.textContent = editing ? 'Saving…' : 'Generating…';
        errSpan.textContent = '';

        try {
            const data = this.collectForm();
            const project = editing
                ? await api.updateProject(this.editingId, data)
                : await api.createProject(data);

            // Hold the id: if the calculation fails (bad coordinates, say), a retry
            // updates this project instead of creating a duplicate.
            this.editingId = project.id;

            const calculated = await api.calculateProject(project.id);

            this.editingId = null;
            this.renderReport(calculated);
            this.showView('report-view');
        } catch (error) {
            errSpan.textContent = error.message;
        } finally {
            btn.disabled = false;
            btn.textContent = label;
        }
    },

    // --- report ------------------------------------------------------------

    async viewProjectReport(project) {
        if (!project.is_calculated) {
            try {
                project = await api.calculateProject(project.id);
            } catch (error) {
                alert(error.message);
                return;
            }
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

        const sourceEl = document.getElementById('r_irradiance_source');
        const fromPvgis = p.irradiance_source === 'pvgis';
        sourceEl.textContent = fromPvgis
            ? `Irradiance source: PVGIS · ${Math.round(p.irradiance_h_annual)} kWh/m²/yr in-plane at ${p.tilt_deg}° tilt, ${p.azimuth_deg}° azimuth · calibration ×${p.irradiance_calibration}`
            : 'Irradiance source: regional estimate. PVGIS was unavailable, so these figures are not site-specific. Recalculate before sending.';
        sourceEl.classList.toggle('is-fallback', !fromPvgis);

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

        this.renderCompliance(p);
        this.renderShadingNote(p);

        // Projection
        document.getElementById('r_lifetime').textContent = `${p.lifetime_gen_mwh.toFixed(1)} MWh`;
        document.getElementById('r_year25').textContent = `${p.year25_output_mwh.toFixed(1)} MWh`;

        const year25Ratio = Math.round((p.year25_output_mwh / mwh) * 100);
        document.getElementById('r_degradation_pct').textContent = `(${year25Ratio}% of Year 1)`;

        this.renderFinancials(p);
    },

    renderCompliance(p) {
        const panel = document.getElementById('r_compliance');
        const issues = p.compliance_json ? JSON.parse(p.compliance_json) : [];
        panel.hidden = issues.length === 0;
        if (panel.hidden) return;

        const errors = issues.filter(i => i.severity === 'error');
        panel.classList.toggle('has-error', errors.length > 0);
        panel.innerHTML = `
            <div class="compliance-title">${errors.length ? 'Not compliant' : 'Compliance notes'}</div>
            <ul>${issues.map(i => `<li class="is-${esc(i.severity)}">${esc(i.message)}</li>`).join('')}</ul>
        `;
    },

    renderShadingNote(p) {
        const note = document.getElementById('r_shading_note');
        note.hidden = p.shading_computed_pct == null;
        if (note.hidden) return;

        const assumed = p.shading_heights_assumed;
        const caveat = assumed
            ? ` Heights were missing from OpenStreetMap for ${assumed} of them and assumed at 6 m, so treat this as an estimate.`
            : '';
        note.textContent =
            `Shading of ${p.shading_computed_pct}% estimated from ${p.shading_neighbour_count} nearby building(s).${caveat}`;
    },

    renderFinancials(p) {
        // Projects without a system cost have no financials; hide rather than show blanks.
        const section = document.getElementById('financial-section');
        section.hidden = p.net_investment_inr == null;
        if (section.hidden) return;

        const set = (id, text) => { document.getElementById(id).textContent = text; };
        set('r_net_investment', formatInr(p.net_investment_inr));
        set('r_subsidy', `${formatInr(p.system_cost_inr)} less ${formatInr(p.subsidy_applied_inr)} subsidy`);
        set('r_payback', p.payback_years == null ? 'Beyond 25 yrs' : `${p.payback_years} yrs`);
        set('r_year1_savings', `${formatInr(p.year1_savings_inr)} saved in year 1`);
        set('r_lifetime_savings', formatInr(p.lifetime_net_savings_inr));
        set('r_irr', p.irr_pct == null ? 'IRR not applicable' : `${p.irr_pct}% IRR`);
        set('r_co2', `${p.co2_offset_tonnes} t`);
        set('r_lcoe', `₹${p.lcoe_inr_per_kwh.toFixed(2)}/kWh over system life`);

        const replacement = document.getElementById('r_replacement_note');
        replacement.hidden = p.inverter_replacement_applied_inr == null;
        if (!replacement.hidden) {
            replacement.textContent =
                `Includes a ${formatInr(p.inverter_replacement_applied_inr)} inverter replacement in year ${p.inverter_replacement_year}.`;
        }

        chartManager.renderCashflowChart('cashflowChart', p.cashflow_json, p.net_investment_inr);
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
