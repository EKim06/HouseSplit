(() => {
  document.querySelectorAll('.toast button').forEach((button) => button.addEventListener('click', () => button.parentElement.remove()));
  window.setTimeout(() => document.querySelectorAll('.toast').forEach((toast) => toast.remove()), 5000);

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        const original = button.textContent;
        button.textContent = 'Copied!';
        window.setTimeout(() => { button.textContent = original; }, 1600);
      } catch (_) {
        window.prompt('Copy this invite link:', button.dataset.copy);
      }
    });
  });

  const purchaseForm = document.querySelector('[data-purchase-form]');
  if (purchaseForm) {
    const updateSplitControls = () => {
      const method = purchaseForm.querySelector('[name="split_method"]:checked')?.value || 'equal';
      const values = purchaseForm.querySelector('[data-split-values]');
      const note = purchaseForm.querySelector('[data-equal-note]');
      values.hidden = method === 'equal';
      note.hidden = method !== 'equal';
      values.querySelectorAll('label').forEach((label) => {
        const member = label.dataset.memberShare;
        const checked = purchaseForm.querySelector(`[name="participant_ids"][value="${member}"]`)?.checked;
        label.hidden = !checked;
        const input = label.querySelector('input');
        input.disabled = !checked || method === 'equal';
        label.querySelector('[data-prefix]').textContent = method === 'fixed' ? '$' : '';
        label.querySelector('[data-suffix]').textContent = method === 'percentage' ? '%' : '';
      });
    };
    purchaseForm.querySelectorAll('[name="split_method"], [name="participant_ids"]').forEach((input) => input.addEventListener('change', updateSplitControls));
    updateSplitControls();
  }

  window.renderHouseSplitCharts = () => {
    const node = document.getElementById('analytics-data');
    if (!node || !window.Chart) return;
    const data = JSON.parse(node.textContent);
    const colors = ['#715458', '#ccb693', '#7a8b6f', '#b36b4a', '#887b70', '#d6c9bb', '#59474a'];
    Chart.defaults.font.family = 'Aptos, Segoe UI, sans-serif';
    Chart.defaults.color = '#776b67';
    const currency = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value / 100);
    const common = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => currency(ctx.raw) } } } };
    new Chart(document.getElementById('monthlyChart'), { type: 'line', data: { labels: Object.keys(data.monthly), datasets: [{ data: Object.values(data.monthly), borderColor: '#715458', backgroundColor: 'rgba(113,84,88,.09)', fill: true, tension: .35, pointRadius: 4, pointBackgroundColor: '#ccb693', pointBorderColor: '#715458', pointBorderWidth: 2 }] }, options: { ...common, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: '#eee7df' }, ticks: { callback: (v) => currency(v) } } } } });
    new Chart(document.getElementById('frontedChart'), { type: 'bar', data: { labels: data.fronted.map((row) => row[0]), datasets: [{ data: data.fronted.map((row) => row[1]), backgroundColor: data.fronted.map((_, i) => colors[i % colors.length]), borderRadius: 5, barThickness: 26 }] }, options: { ...common, indexAxis: 'y', scales: { x: { beginAtZero: true, grid: { color: '#eee7df' }, ticks: { callback: (v) => currency(v) } }, y: { grid: { display: false } } } } });
    new Chart(document.getElementById('categoryChart'), { type: 'doughnut', data: { labels: Object.keys(data.categories), datasets: [{ data: Object.values(data.categories), backgroundColor: Object.keys(data.categories).map((_, i) => colors[i % colors.length]), borderColor: '#fffdf9', borderWidth: 4, hoverOffset: 3 }] }, options: { ...common, cutout: '70%' } });
  };
  window.renderHouseSplitCharts();
})();
