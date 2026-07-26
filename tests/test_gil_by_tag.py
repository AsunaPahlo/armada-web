"""Tests for the gil/day per-tag breakdown in dashboard data."""


def test_counts_gil_in_each_tag_of_a_multi_tag_fc():
    from app.services.fleet_manager import compute_gil_per_day_by_tag
    fc_summaries = [
        {'gil_per_day': 100, 'tags': [{'id': 1, 'name': 'Main', 'color': 'primary'},
                                      {'id': 2, 'name': 'EU', 'color': 'info'}]},
        {'gil_per_day': 50, 'tags': [{'id': 1, 'name': 'Main', 'color': 'primary'}]},
    ]
    by_id = {b['tag_id']: b for b in compute_gil_per_day_by_tag(fc_summaries)}
    assert by_id[1]['gil_per_day'] == 150  # 100 + 50
    assert by_id[1]['fc_count'] == 2
    assert by_id[1]['tag_name'] == 'Main'
    assert by_id[1]['color'] == 'primary'
    assert by_id[2]['gil_per_day'] == 100
    assert by_id[2]['fc_count'] == 1


def test_untagged_bucket_is_last_and_aggregates_untagged_fcs():
    from app.services.fleet_manager import compute_gil_per_day_by_tag
    fc_summaries = [
        {'gil_per_day': 100, 'tags': [{'id': 1, 'name': 'Main', 'color': 'primary'}]},
        {'gil_per_day': 30, 'tags': []},
        {'gil_per_day': 20, 'tags': []},
    ]
    result = compute_gil_per_day_by_tag(fc_summaries)
    assert result[-1] == {'tag_id': None, 'tag_name': 'Untagged',
                          'color': 'secondary', 'gil_per_day': 50, 'fc_count': 2}


def test_tag_buckets_sorted_by_gil_descending():
    from app.services.fleet_manager import compute_gil_per_day_by_tag
    fc_summaries = [
        {'gil_per_day': 10, 'tags': [{'id': 1, 'name': 'Small', 'color': 'secondary'}]},
        {'gil_per_day': 200, 'tags': [{'id': 2, 'name': 'Big', 'color': 'primary'}]},
    ]
    result = compute_gil_per_day_by_tag(fc_summaries)
    assert [b['tag_id'] for b in result] == [2, 1]


def test_untagged_bucket_omitted_when_all_fcs_tagged():
    from app.services.fleet_manager import compute_gil_per_day_by_tag
    fc_summaries = [
        {'gil_per_day': 100, 'tags': [{'id': 1, 'name': 'Main', 'color': 'primary'}]},
    ]
    result = compute_gil_per_day_by_tag(fc_summaries)
    assert all(b['tag_id'] is not None for b in result)
    assert len(result) == 1


def test_empty_input_returns_empty_list():
    from app.services.fleet_manager import compute_gil_per_day_by_tag
    assert compute_gil_per_day_by_tag([]) == []


def test_get_dashboard_data_includes_gil_per_day_by_tag_list(app, db):
    from app.services import get_fleet_manager
    data = get_fleet_manager().get_dashboard_data()
    assert isinstance(data.get('gil_per_day_by_tag'), list)
