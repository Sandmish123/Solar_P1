const chartManager = {
    chartInstance: null,

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
    }
};
