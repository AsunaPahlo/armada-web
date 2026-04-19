"""FC Credits tracker service: snapshot upsert + report generation."""
from datetime import date, timedelta


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
