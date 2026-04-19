# FC Detail Loot Performance Chart

## Summary

Add a "Loot Performance" section to the FC detail page (`/fc/<fc_id>`) showing a Chart.js line chart of daily gil earned over time, with a day selector (7/14/30/90/All).

## Architecture

### Backend: New JSON API endpoint

- `GET /fc/<fc_id>/loot-performance?days=30&tz_offset=0`
- Queries `VoyageLoot` filtered by `fc_id`, groups by date, returns daily totals
- Returns: `{ daily_totals: [{date, voyages, total_gil}], avg_gil_per_day, total_gil, total_voyages }`

### Service layer

- Add `get_fc_daily_totals(fc_id, days, tz_offset_minutes)` method to `LootTracker`
- Focused query filtering `VoyageLoot` by `fc_id`, grouped by date with timezone adjustment

### Frontend

- New card section in `fc_detail.html` after submarines table, before activity log
- Day selector buttons (7/14/30/90/All) matching existing UI pattern
- Chart.js line chart rendering daily gil values
- AJAX loading on page load and day selector change

## Data Flow

```
Day selector click -> JS fetch /fc/<id>/loot-performance?days=N
  -> Route calls loot_tracker.get_fc_daily_totals(fc_id, days, tz)
    -> SQLite query: VoyageLoot WHERE fc_id=X GROUP BY date
  -> JSON response -> Chart.js renders line chart
```

## Files to Modify

1. `app/services/loot_tracker.py` - add `get_fc_daily_totals()` method
2. `app/routes/stats.py` - add `/fc/<fc_id>/loot-performance` endpoint
3. `app/templates/fc_detail.html` - add Loot Performance card with chart + day selector
