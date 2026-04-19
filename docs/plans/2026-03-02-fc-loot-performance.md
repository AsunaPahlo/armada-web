# FC Loot Performance Chart — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a daily loot/gil line chart with day selector to the FC detail page so users can see how a specific FC is performing over time.

**Architecture:** New AJAX endpoint `/fc/<fc_id>/loot-performance` returns daily totals for a single FC. A new `get_fc_daily_totals()` method on `LootTracker` handles the DB query. The frontend renders a Chart.js line chart in a new card section between the submarines table and activity log.

**Tech Stack:** Flask, SQLAlchemy, Chart.js 4.4.1 (CDN), Bootstrap 5

---

### Task 1: Add `get_fc_daily_totals()` to LootTracker

**Files:**
- Modify: `app/services/loot_tracker.py` (insert after line 623, after the `get_daily_totals` method)

**Step 1: Add the method**

Insert after the `get_daily_totals` method (after line 623):

```python
def get_fc_daily_totals(self, fc_id: str, days: int = 30, tz_offset_minutes: int = 0) -> dict:
    """Get daily loot totals for a specific FC with timezone adjustment."""
    from sqlalchemy import func, and_

    filters = [VoyageLoot.fc_id == str(fc_id)]
    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        filters.append(VoyageLoot.captured_at >= cutoff)

    # Total counts
    count_query = VoyageLoot.query.filter(and_(*filters))
    total_voyages = count_query.count()

    gil_query = db.session.query(func.sum(VoyageLoot.total_gil_value)).filter(and_(*filters))
    total_gil = gil_query.scalar() or 0

    # Daily totals with timezone adjustment
    tz_offset_hours = -tz_offset_minutes / 60
    tz_modifier = f'{tz_offset_hours:+.1f} hours'
    local_datetime = func.datetime(VoyageLoot.captured_at, tz_modifier)
    local_date = func.date(local_datetime)

    daily_query = db.session.query(
        local_date.label('date'),
        func.count(VoyageLoot.id).label('voyages'),
        func.sum(VoyageLoot.total_gil_value).label('total_gil')
    ).filter(and_(*filters))

    daily_totals = daily_query.group_by(local_date).order_by(local_date).all()

    num_days = len(daily_totals)
    avg_gil_per_day = round(total_gil / num_days, 0) if num_days > 0 else 0

    return {
        'total_voyages': total_voyages,
        'total_gil': total_gil,
        'avg_gil_per_day': avg_gil_per_day,
        'daily_totals': [
            {'date': str(d.date), 'voyages': d.voyages, 'total_gil': d.total_gil}
            for d in daily_totals
        ]
    }
```

**Step 2: Verify no syntax errors**

Run: `python -c "from app.services.loot_tracker import loot_tracker; print('OK')"`

**Step 3: Commit**

```bash
git add app/services/loot_tracker.py
git commit -m "feat: add get_fc_daily_totals to LootTracker for FC-specific loot stats"
```

---

### Task 2: Add `/fc/<fc_id>/loot-performance` endpoint

**Files:**
- Modify: `app/routes/stats.py` (insert after the `fc_detail` route, around line 668)

**Step 1: Add the endpoint**

Insert after the `fc_detail` route (after line 668):

```python
@stats_bp.route('/fc/<fc_id>/loot-performance')
@login_required
def fc_loot_performance(fc_id):
    """API endpoint for FC-specific daily loot data."""
    from app.services.loot_tracker import loot_tracker

    days = request.args.get('days', 30, type=int)
    if days != 0:
        days = min(max(days, 1), 365)

    tz_offset = request.args.get('tz', 0, type=int)
    tz_offset = max(-720, min(840, tz_offset))

    result = loot_tracker.get_fc_daily_totals(
        fc_id=str(fc_id), days=days, tz_offset_minutes=tz_offset
    )
    return jsonify(result)
```

**Step 2: Verify no syntax errors**

Run: `python -c "from app.routes.stats import stats_bp; print('OK')"`

**Step 3: Commit**

```bash
git add app/routes/stats.py
git commit -m "feat: add /fc/<fc_id>/loot-performance API endpoint"
```

---

### Task 3: Add Loot Performance chart section to fc_detail.html

**Files:**
- Modify: `app/templates/fc_detail.html` (insert between line 75 and 76 — after submarines card closes, before Activity Log card)

**Step 1: Add the Chart.js CDN script**

Find the `{% block content %}` or `<script>` area. The chart script will need Chart.js loaded. Check if there's a `{% block scripts %}` or similar — if not, include the CDN script inline in the new section's script block.

**Step 2: Add the Loot Performance card HTML**

Insert between line 75 (end of submarines card) and line 76 (Activity Log card):

```html
<!-- Loot Performance -->
<div class="card">
    <div class="card-header py-2 d-flex justify-content-between align-items-center">
        <span><i class="bi bi-graph-up me-2"></i>Loot Performance</span>
        <div class="btn-group btn-group-sm" id="loot-days-selector">
            <button class="btn btn-outline-secondary py-0 px-2" data-days="7">7D</button>
            <button class="btn btn-outline-secondary py-0 px-2 active" data-days="30">30D</button>
            <button class="btn btn-outline-secondary py-0 px-2" data-days="90">90D</button>
            <button class="btn btn-outline-secondary py-0 px-2" data-days="0">All</button>
        </div>
    </div>
    <div class="card-body py-2">
        <div id="loot-chart-container" style="height: 220px; position: relative;">
            <canvas id="loot-performance-chart"></canvas>
        </div>
        <div id="loot-chart-loading" class="text-center text-muted py-3">
            <div class="spinner-border spinner-border-sm" role="status"></div>
            <span class="ms-2">Loading loot data...</span>
        </div>
        <div id="loot-chart-empty" class="text-center text-muted py-3" style="display:none;">
            <i class="bi bi-inbox me-2"></i>No loot data available for this period
        </div>
        <div class="d-flex justify-content-around mt-2" id="loot-summary-cards" style="display:none !important;">
            <div class="text-center">
                <div class="text-muted small">Avg Gil/Day</div>
                <div class="fw-bold" id="loot-avg-gil-day">-</div>
            </div>
            <div class="text-center">
                <div class="text-muted small">Total Gil</div>
                <div class="fw-bold" id="loot-total-gil">-</div>
            </div>
            <div class="text-center">
                <div class="text-muted small">Voyages</div>
                <div class="fw-bold" id="loot-total-voyages">-</div>
            </div>
        </div>
    </div>
</div>
```

**Step 3: Add the JavaScript**

Add inside the existing `<script>` block at the bottom of the template (before the closing `</script>` tag), or in a new `<script>` block after the Chart.js CDN:

```javascript
// Loot Performance Chart
(function() {
    const chartCanvas = document.getElementById('loot-performance-chart');
    const loadingEl = document.getElementById('loot-chart-loading');
    const emptyEl = document.getElementById('loot-chart-empty');
    const summaryEl = document.getElementById('loot-summary-cards');
    const dayButtons = document.querySelectorAll('#loot-days-selector button');
    let lootChart = null;

    function formatGil(value) {
        if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
        if (value >= 1000) return (value / 1000).toFixed(0) + 'K';
        return value;
    }

    function loadLootData(days) {
        loadingEl.style.display = '';
        emptyEl.style.display = 'none';
        summaryEl.style.setProperty('display', 'none', 'important');
        chartCanvas.style.display = 'none';

        const url = new URL(`{{ url_for("stats.fc_loot_performance", fc_id=fc_id) }}`, window.location.origin);
        url.searchParams.set('days', days);
        url.searchParams.set('tz', new Date().getTimezoneOffset());

        fetch(url)
            .then(r => r.json())
            .then(data => {
                loadingEl.style.display = 'none';
                const dailyTotals = data.daily_totals || [];

                if (dailyTotals.length === 0) {
                    emptyEl.style.display = '';
                    return;
                }

                chartCanvas.style.display = '';
                summaryEl.style.setProperty('display', 'flex', 'important');

                // Update summary cards
                document.getElementById('loot-avg-gil-day').textContent = formatGil(data.avg_gil_per_day);
                document.getElementById('loot-total-gil').textContent = formatGil(data.total_gil);
                document.getElementById('loot-total-voyages').textContent = data.total_voyages.toLocaleString();

                // Destroy previous chart if exists
                if (lootChart) lootChart.destroy();

                lootChart = new Chart(chartCanvas.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: dailyTotals.map(d => d.date.slice(5)),
                        datasets: [{
                            label: 'Gil',
                            data: dailyTotals.map(d => d.total_gil),
                            borderColor: 'rgba(237, 177, 54, 1)',
                            backgroundColor: 'rgba(237, 177, 54, 0.2)',
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }, {
                            label: 'Voyages',
                            data: dailyTotals.map(d => d.voyages),
                            borderColor: 'rgba(99, 179, 237, 1)',
                            backgroundColor: 'rgba(99, 179, 237, 0.2)',
                            fill: false,
                            tension: 0.3,
                            yAxisID: 'y1'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                labels: { color: 'rgba(255,255,255,0.7)' }
                            }
                        },
                        scales: {
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                beginAtZero: true,
                                grid: { color: 'rgba(255,255,255,0.1)' },
                                ticks: {
                                    color: 'rgba(237, 177, 54, 0.8)',
                                    callback: function(value) {
                                        return formatGil(value);
                                    }
                                },
                                title: {
                                    display: true,
                                    text: 'Gil',
                                    color: 'rgba(237, 177, 54, 0.8)'
                                }
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                beginAtZero: true,
                                grid: { drawOnChartArea: false },
                                ticks: { color: 'rgba(99, 179, 237, 0.8)' },
                                title: {
                                    display: true,
                                    text: 'Voyages',
                                    color: 'rgba(99, 179, 237, 0.8)'
                                }
                            },
                            x: {
                                grid: { color: 'rgba(255,255,255,0.1)' },
                                ticks: { color: 'rgba(255,255,255,0.7)' }
                            }
                        }
                    }
                });
            })
            .catch(err => {
                loadingEl.style.display = 'none';
                emptyEl.style.display = '';
                console.error('Error loading loot performance:', err);
            });
    }

    // Day selector buttons
    dayButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            dayButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            loadLootData(btn.dataset.days);
        });
    });

    // Initial load (30 days)
    loadLootData(30);
})();
```

**Step 4: Add the Chart.js CDN import**

The `fc_detail.html` template needs Chart.js loaded. Add this before the loot performance script:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
```

**Step 5: Test manually**

Open the FC detail page in the browser and verify:
- Chart loads with 30-day data by default
- Day selector buttons switch time ranges
- Empty state shows if no loot data exists
- Summary cards show avg gil/day, total gil, total voyages

**Step 6: Commit**

```bash
git add app/templates/fc_detail.html
git commit -m "feat: add loot performance chart to FC detail page"
```
