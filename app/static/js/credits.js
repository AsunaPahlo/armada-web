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

  function renderCards(cards) {
    document.getElementById('card-week-earned').textContent = fmt(cards.week_earned);
    document.getElementById('card-month-earned').textContent = fmt(cards.month_earned);
    document.getElementById('card-alltime-earned').textContent = fmt(cards.all_time_earned);
    document.getElementById('card-current-balance').textContent = fmt(cards.current_balance);
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
      ul.innerHTML = '<li class="list-group-item text-muted">No FCs yet</li>';
      return;
    }
    all.sort((a, b) => (b.current_balance || 0) - (a.current_balance || 0));
    for (const fc of all) {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex align-items-center justify-content-between';
      const label = document.createElement('div');
      label.innerHTML = `<strong>${fc.fc_name || fc.fc_id}</strong>`
        + `<span class="text-muted ms-2">${fc.world || ''}</span>`
        + `<span class="badge bg-secondary ms-2">${fmt(fc.current_balance)}</span>`;
      const switchWrap = document.createElement('div');
      switchWrap.className = 'form-check form-switch';
      const input = document.createElement('input');
      input.className = 'form-check-input';
      input.type = 'checkbox';
      input.role = 'switch';
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
    const resp = await fetch(`/credits/data?days=${days}`);
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
