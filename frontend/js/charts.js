// Chart.js animates by default; honour the OS reduced-motion setting.
const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const chartManager = {
    chartInstance: null,
    cashflowInstance: null,

    renderMonthlyChart(canvasId, jsonDataStr) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        let data = [];
        try {
            data = JSON.parse(jsonDataStr);
        } catch (e) {
            console.warn("Invalid chart data");
            return;
        }

        const labels = data.map(d => d.month.charAt(0)); // J, F, M, A...
        const values = data.map(d => d.value_kwh);

        // Colors: Blue for Regular, Yellow for Monsoon
        const bgColors = data.map(d => d.season === 'Monsoon' ? '#fbbc04' : '#4285f4');

        if (this.chartInstance) {
            this.chartInstance.destroy();
        }

        this.chartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: bgColors,
                    borderRadius: 2,
                    barPercentage: 0.9,
                    categoryPercentage: 0.95
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                ...(prefersReducedMotion() && { animation: false }),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                let label = context.raw || '';
                                if (label) label += ' kWh';
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 10 } },
                        border: { display: false }
                    },
                    y: {
                        display: false, // Hide y axis like in UI reference
                        grid: { display: false },
                        border: { display: false }
                    }
                }
            }
        });
    },

    // Cumulative net position from year 0 (the net investment) to year 25.
    // Red below break-even, green above.
    renderCashflowChart(canvasId, jsonDataStr, netInvestment) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        let rows = [];
        try {
            rows = JSON.parse(jsonDataStr);
        } catch (e) {
            console.warn("Invalid cashflow data");
            return;
        }

        const labels = ['0', ...rows.map(r => String(r.year))];
        const values = [-netInvestment, ...rows.map(r => r.cumulative_inr)];
        const red = '#ef4444';
        const green = '#10b981';

        if (this.cashflowInstance) {
            this.cashflowInstance.destroy();
        }

        this.cashflowInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    data: values,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.25,
                    fill: { target: 'origin', above: 'rgba(16, 185, 129, 0.12)', below: 'rgba(239, 68, 68, 0.12)' },
                    segment: { borderColor: s => (s.p1.parsed.y < 0 ? red : green) },
                    borderColor: green
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                ...(prefersReducedMotion() && { animation: false }),
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => `Year ${items[0].label}`,
                            label: context => formatInr(context.raw)
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 10 }, maxTicksLimit: 6 },
                        title: { display: true, text: 'Year', font: { size: 11 } },
                        border: { display: false }
                    },
                    y: {
                        // Lakhs keep the axis short: ₹-4.5L ... ₹21.8L.
                        ticks: { font: { size: 10 }, callback: v => `₹${(v / 1e5).toFixed(1)}L` },
                        grid: { color: ctx => (ctx.tick.value === 0 ? '#94a3b8' : 'rgba(148, 163, 184, 0.15)') },
                        border: { display: false }
                    }
                }
            }
        });
    }
};
