(function () {
  'use strict';

  let chart = null;
  let currentDays = 30;

  function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString();
  }

  function setDayActive(days) {
    document.querySelectorAll('#credits-day-selector button').forEach(b => {
      b.classList.toggle('active', String(b.dataset.days) === String(days));
    });
  }

  function periodLabel(days) {
    switch (Number(days)) {
      case 0: return 'All time';
      case 7: return 'Last 7 days';
      case 14: return 'Last 14 days';
      case 30: return 'Last 30 days';
      case 90: return 'Last 90 days';
      case 365: return 'Last year';
      default: return `Last ${days} days`;
    }
  }

  function renderCards(cards) {
    document.getElementById('card-period-earned').textContent = fmt(cards.period_earned);
    document.getElementById('card-period-used').textContent = fmt(cards.period_used);
    document.getElementById('card-current-balance').textContent = fmt(cards.current_balance);

    const net = Number(cards.period_net) || 0;
    const netEl = document.getElementById('card-period-net');
    netEl.textContent = (net > 0 ? '+' : '') + fmt(net);
    netEl.classList.toggle('text-success', net >= 0);
    netEl.classList.toggle('text-danger', net < 0);

    const label = periodLabel(cards.days);
    document.getElementById('card-period-earned-sub').textContent = label;
    document.getElementById('card-period-used-sub').textContent = label;
    document.getElementById('card-period-net-sub').textContent = label;
  }

  function renderChart(series) {
    const canvas = document.getElementById('credits-chart');
    const labels = series.map(p => p.date);
    const data = series.map(p => p.balance);

    if (chart) {
      chart.data.labels = labels;
      chart.data.datasets[0].data = data;
      chart.update();
      return;
    }
    chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Total FC Credits',
          data: data,
          borderColor: '#667eea',
          backgroundColor: 'rgba(102, 126, 234, 0.15)',
          fill: true,
          tension: 0.2,
          pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: false, ticks: { callback: v => Number(v).toLocaleString() } } }
      }
    });
  }

  function renderFcList(included, excluded) {
    const ul = document.getElementById('credits-fc-list');
    ul.innerHTML = '';
    const all = included.concat(excluded);
    if (all.length === 0) {
      ul.innerHTML = '<li class="list-group-item bg-transparent text-muted">No FCs yet</li>';
      return;
    }
    all.sort((a, b) => (b.current_balance || 0) - (a.current_balance || 0));
    for (const fc of all) {
      const li = document.createElement('li');
      li.className = 'list-group-item bg-transparent d-flex align-items-center justify-content-between';
      const label = document.createElement('div');
      const name = document.createElement('strong');
      name.textContent = fc.fc_name || fc.fc_id;
      const world = document.createElement('span');
      world.className = 'text-muted ms-2';
      world.textContent = fc.world || '';
      const balance = document.createElement('span');
      balance.className = 'badge bg-secondary ms-2';
      balance.textContent = fmt(fc.current_balance);
      label.append(name, world, balance);
      const switchWrap = document.createElement('div');
      switchWrap.className = 'form-check form-switch';
      const input = document.createElement('input');
      input.className = 'form-check-input';
      input.type = 'checkbox';
      input.setAttribute('role', 'switch');
      input.checked = !fc.excluded;  // checked == included
      input.addEventListener('change', () => toggleFc(fc.fc_id, !input.checked));
      switchWrap.appendChild(input);
      li.appendChild(label);
      li.appendChild(switchWrap);
      ul.appendChild(li);
    }
  }

  function showEmpty(isEmpty) {
    document.getElementById('credits-empty').classList.toggle('d-none', !isEmpty);
    document.getElementById('credits-content').classList.toggle('d-none', isEmpty);
  }

  async function loadData(days) {
    currentDays = days;
    setDayActive(days);
    const tz = new Date().getTimezoneOffset();
    const resp = await fetch(`/credits/data?days=${days}&tz=${tz}`);
    if (!resp.ok) {
      console.error('Failed to load credits data', resp.status);
      return;
    }
    const body = await resp.json();
    const isEmpty = body.included_fcs.length === 0 && body.excluded_fcs.length === 0;
    showEmpty(isEmpty);
    if (isEmpty) return;
    renderCards(body.cards);
    renderChart(body.series);
    renderFcList(body.included_fcs, body.excluded_fcs);
  }

  async function toggleFc(fcId, excluded) {
    const resp = await fetch('/credits/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fc_id: fcId, excluded: excluded })
    });
    if (!resp.ok) {
      console.error('Toggle failed', resp.status);
      return;
    }
    await loadData(currentDays);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('#credits-day-selector button').forEach(btn => {
      btn.addEventListener('click', () => {
        const d = parseInt(btn.dataset.days, 10);
        loadData(Number.isFinite(d) ? d : 30);
      });
    });
    loadData(30);
  });
})();
