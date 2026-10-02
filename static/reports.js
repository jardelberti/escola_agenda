document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('report-filters');
  const compare = document.getElementById('compare');
  const custom = document.getElementById('compare-dates');
  function comparisonFields() {
    const enabled = compare.value === 'custom';
    custom.hidden = !enabled;
    custom.querySelectorAll('input').forEach(input => { input.disabled = !enabled; input.required = enabled; });
  }
  compare.addEventListener('change', comparisonFields);
  comparisonFields();
  ['start_date', 'end_date'].forEach(name => document.getElementById(name).addEventListener('change', () => { document.getElementById('preset').value = 'custom'; }));
  document.getElementById('preset').addEventListener('change', () => {
    if (document.getElementById('preset').value !== 'custom') form.requestSubmit();
  });
  document.getElementById('print-report')?.addEventListener('click', () => window.print());
  const dataElement = document.getElementById('report-chart-data');
  if (!dataElement || typeof Chart === 'undefined') return;
  const data = JSON.parse(dataElement.textContent);
  const currentLabel = data.currentPeriod;
  const previousLabel = data.previousPeriod;
  const charts = data.charts;
  const base = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 10 } } } } };
  function paired(id, chart, horizontal) {
    if (!chart.labels.length || ![...chart.current, ...(data.compare ? chart.previous : [])].some(n => n > 0)) return;
    const datasets = [{ label: currentLabel, data: chart.current, backgroundColor: '#3b82f6', borderRadius: 3, maxBarThickness: 20 }];
    if (data.compare) datasets.push({ label: previousLabel, data: chart.previous, backgroundColor: '#94a3b8', borderRadius: 3, maxBarThickness: 20 });
    new Chart(document.getElementById(id), { type: 'bar', data: { labels: chart.labels, datasets }, options: { ...base, indexAxis: horizontal ? 'y' : 'x',
      scales: { [horizontal ? 'x' : 'y']: { beginAtZero: true, ticks: { precision: 0 } } } } });
  }
  paired('reportResourceChart', charts.resource, true);
  paired('reportShiftChart', charts.shift, false);
  for (const [id, chart, label] of [['reportEvolutionChart', charts.evolution, 'Reservas'], ['reportWeekdayChart', charts.weekday, 'Reservas']]) {
    if (!chart.values.some(n => n > 0)) continue;
    new Chart(document.getElementById(id), { type: 'bar', data: { labels: chart.labels, datasets: [{ label, data: chart.values, backgroundColor: '#60a5fa', borderRadius: 3, maxBarThickness: 24 }] },
      options: { ...base, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { ticks: { maxRotation: 0, maxTicksLimit: 10 } } } } });
  }
  window.addEventListener('beforeprint', () => Object.values(Chart.instances).forEach(chart => chart.resize()));
  window.addEventListener('afterprint', () => Object.values(Chart.instances).forEach(chart => chart.resize()));
});
