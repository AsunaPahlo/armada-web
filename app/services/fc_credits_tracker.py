"""FC Credits tracker service: snapshot upsert + report generation."""
from datetime import date, datetime, timedelta


def positive_delta_sum(snapshots: list) -> int:
    """Sum of positive deltas between consecutive snapshots.

    Args:
        snapshots: list of (date, credits) tuples, sorted ascending by date.

    Returns:
        Sum of increases (spending decreases are ignored).
    """
    if len(snapshots) < 2:
        return 0
    total = 0
    for i in range(1, len(snapshots)):
        delta = snapshots[i][1] - snapshots[i - 1][1]
        if delta > 0:
            total += delta
    return total


def aggregate_daily_balance(per_fc: dict, start: date, end: date) -> list:
    """Produce one (date, total_balance) tuple per day between start and end inclusive.

    For each day, sum the last-known balance of every FC that has a snapshot on or before that day.
    FCs with no snapshot yet contribute 0.

    Args:
        per_fc: dict mapping fc_id -> list of (date, credits) tuples, sorted ascending.
        start: first date in the output range.
        end: last date in the output range.

    Returns:
        List of (date, total_balance) tuples, one per day in [start, end].
    """
    if not per_fc:
        return []

    # Index snapshots by fc_id for carry-forward lookup
    result = []
    # For each FC, track the index of the "next" snapshot to consider
    indices = {fc_id: 0 for fc_id in per_fc}
    # Last known balance per FC (carry-forward)
    last_known = {fc_id: 0 for fc_id in per_fc}

    current = start
    while current <= end:
        # Advance each FC's pointer while the next snapshot's date <= current
        for fc_id, snaps in per_fc.items():
            idx = indices[fc_id]
            while idx < len(snaps) and snaps[idx][0] <= current:
                last_known[fc_id] = snaps[idx][1]
                idx += 1
            indices[fc_id] = idx
        total = sum(last_known.values())
        result.append((current, total))
        current += timedelta(days=1)
    return result


def _fc_info_lookup(fc_id: str) -> tuple:
    """Return (fc_name, world) for an fc_id by looking it up in the live FleetManager.

    Falls back to (fc_id, "") if the FC is not currently in plugin data. Wrapped in a
    function so tests can monkeypatch it without pulling in the FleetManager singleton.
    """
    try:
        from app.services import get_fleet_manager
        fleet = get_fleet_manager()
        data = fleet.get_dashboard_data() or {}
        summaries = data.get('fc_summaries', [])
        # fc_summaries may be a list of dicts or a dict keyed by fc_id depending on caller
        if isinstance(summaries, dict):
            summaries = list(summaries.values())
        for fc in summaries:
            if str(fc.get('fc_id')) == str(fc_id):
                return (fc.get('fc_name', fc_id), fc.get('world', ''))
    except Exception:
        pass
    return (fc_id, "")


class FCCreditsTracker:
    """Service for FC credits snapshots and report generation."""

    @staticmethod
    def record_snapshot(fc_id: str, credits: int) -> None:
        """Upsert today's snapshot for an FC. Latest value wins within a day."""
        from app import db
        from app.models.fc_credits_snapshot import FCCreditsSnapshot

        today = date.today()
        row = FCCreditsSnapshot.query.filter_by(
            fc_id=str(fc_id), snapshot_date=today
        ).first()
        if row:
            row.credits = int(credits)
            row.updated_at = datetime.utcnow()
        else:
            row = FCCreditsSnapshot(
                fc_id=str(fc_id),
                snapshot_date=today,
                credits=int(credits),
                updated_at=datetime.utcnow()
            )
            db.session.add(row)
        db.session.commit()

    @staticmethod
    def get_report(days: int, exclude_fc_ids: set) -> dict:
        """Build the full credits report for the /credits page.

        Args:
            days: number of days for chart window and week/month cards.
                  0 means all history for the chart.
            exclude_fc_ids: set of fc_id strings to exclude from chart + stat cards.

        Returns:
            dict with keys: series, cards, included_fcs, excluded_fcs.
        """
        from app.models.fc_credits_snapshot import FCCreditsSnapshot

        exclude_fc_ids = {str(x) for x in exclude_fc_ids}
        all_rows = FCCreditsSnapshot.query.order_by(
            FCCreditsSnapshot.fc_id, FCCreditsSnapshot.snapshot_date
        ).all()

        # Group by fc_id
        per_fc_all = {}
        for r in all_rows:
            per_fc_all.setdefault(r.fc_id, []).append((r.snapshot_date, r.credits))

        if not per_fc_all:
            return {
                "series": [],
                "cards": {"week_earned": 0, "month_earned": 0,
                          "all_time_earned": 0, "current_balance": 0},
                "included_fcs": [],
                "excluded_fcs": [],
            }

        today = date.today()
        included_fc_ids = [fid for fid in per_fc_all if fid not in exclude_fc_ids]
        excluded_fc_ids_present = [fid for fid in per_fc_all if fid in exclude_fc_ids]

        # Chart series: aggregate over included FCs
        per_fc_included = {fid: per_fc_all[fid] for fid in included_fc_ids}
        if days > 0:
            # Chart window: last N days up to today
            start = today - timedelta(days=days - 1)
        else:
            # All time: from the earliest snapshot date across included FCs
            earliest = min(
                (snaps[0][0] for snaps in per_fc_included.values() if snaps),
                default=today
            )
            start = earliest
        agg = aggregate_daily_balance(per_fc_included, start, today)
        series = [{"date": d.isoformat(), "balance": b} for d, b in agg]

        # Cards (only over included FCs)
        def window_delta_sum(window_days: int) -> int:
            if window_days <= 0:
                # All-time
                return sum(positive_delta_sum(per_fc_included[fid]) for fid in included_fc_ids)
            cutoff = today - timedelta(days=window_days - 1)
            total = 0
            for fid in included_fc_ids:
                snaps = per_fc_included[fid]
                # Include the last snapshot strictly before the cutoff as the "anchor"
                # so the first day's delta reflects earnings relative to the entering balance.
                anchor = None
                in_window = []
                for d, c in snaps:
                    if d < cutoff:
                        anchor = (d, c)
                    else:
                        in_window.append((d, c))
                windowed = ([anchor] if anchor else []) + in_window
                total += positive_delta_sum(windowed)
            return total

        week_earned = window_delta_sum(7)
        month_earned = window_delta_sum(30)
        all_time_earned = sum(positive_delta_sum(per_fc_all[fid]) for fid in included_fc_ids)
        current_balance = sum(
            per_fc_included[fid][-1][1] for fid in included_fc_ids if per_fc_included[fid]
        )

        # FC lists for the toggle UI
        def fc_entry(fc_id, excluded: bool) -> dict:
            name, world = _fc_info_lookup(fc_id)
            snaps = per_fc_all.get(fc_id, [])
            current = snaps[-1][1] if snaps else 0
            return {
                "fc_id": fc_id,
                "fc_name": name,
                "world": world,
                "current_balance": current,
                "excluded": excluded,
            }

        included_fcs = [fc_entry(fid, False) for fid in included_fc_ids]
        excluded_fcs = [fc_entry(fid, True) for fid in excluded_fc_ids_present]

        return {
            "series": series,
            "cards": {
                "week_earned": week_earned,
                "month_earned": month_earned,
                "all_time_earned": all_time_earned,
                "current_balance": current_balance,
            },
            "included_fcs": included_fcs,
            "excluded_fcs": excluded_fcs,
        }
