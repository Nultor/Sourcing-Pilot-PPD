"""The agent's Cube tools (pipeline/tools/cube.py) on the saturation and breach marts.

Checks that each named tool runs the query it promises, and that the generic fallback
rejects names Cube doesn't know. Needs loaded data and Cube up; skips otherwise.
"""
import pytest
from pydantic import ValidationError

from pipeline.tools.cube import (compare_snapshots, get_capacity_breaches, get_component_breach,
                                 get_component_timeline, get_top_saturated, list_metrics, query_metric)
from tests.ground_truth import LATEST, SNAPSHOTS, ground_truth

pytestmark = pytest.mark.usefixtures("cube")


@pytest.mark.parametrize("scenario", ["baseline", "stretch"])
def test_top_saturated_is_worst_first_and_limited(scenario):
    rows = get_top_saturated.invoke({"scenario": scenario, "limit": 5})
    peaks = [float(r[f"saturation.peak_{scenario}_saturation"]) for r in rows]
    assert len(rows) == 5
    assert peaks == sorted(peaks, reverse=True)


def test_top_saturated_finds_the_worst_planted_case():
    cases = ground_truth(LATEST, "planted_cases.csv")
    worst = cases.loc[cases.peak_stretch_saturation.idxmax(), "ac_code"]
    assert get_top_saturated.invoke({"limit": 1})[0]["saturation.ac_code"] == worst


def test_top_saturated_only_accepts_known_scenarios():
    with pytest.raises(ValidationError):
        get_top_saturated.invoke({"scenario": "worst"})


def test_component_timeline_covers_the_forecast_horizon_in_order():
    truth = ground_truth(LATEST, "saturation.csv")
    ac = truth.ac_code.iloc[0]
    rows = get_component_timeline.invoke({"ac_code": ac})
    assert [r["saturation.forecast_quarter"] for r in rows] == sorted(truth[truth.ac_code == ac].quarter)


def test_component_timeline_of_unknown_component_is_empty():
    assert get_component_timeline.invoke({"ac_code": "000000000"}) == []


def test_compare_snapshots_returns_every_snapshot_in_order():
    ac = ground_truth(LATEST, "planted_cases.csv").ac_code.iloc[0]
    rows = compare_snapshots.invoke({"ac_code": ac})
    assert [r["saturation_history.snapshot_quarter"] for r in rows] == SNAPSHOTS


def test_list_metrics_shows_both_cubes_and_hides_the_key():
    cubes = {c["cube"]: c for c in list_metrics.invoke({})}
    assert {"saturation", "saturation_history"} <= set(cubes)
    assert "saturation.baseline_saturation" in cubes["saturation"]["measures"]
    assert "saturation.saturation_key" not in cubes["saturation"]["dimensions"]


def test_query_metric_runs_a_valid_query():
    rows = query_metric.invoke({"measures": ["saturation.baseline_saturation"],
                                "dimensions": ["saturation.forecast_quarter"], "limit": 3})
    assert len(rows) == 3


@pytest.mark.parametrize("query", [
    {"measures": ["saturation.made_up"]},
    {"measures": ["saturation.baseline_saturation"], "dimensions": ["saturation.supplier"]},
    {"measures": ["saturation.baseline_saturation"],
     "filters": [{"member": "saturation.plant", "operator": "equals", "values": ["X"]}]},
])
def test_query_metric_rejects_unknown_names(query):
    result = query_metric.invoke(query)
    assert isinstance(result, str) and result.startswith("Unknown names")


def test_capacity_breaches_lists_every_planted_problem_soonest_first():
    cases = ground_truth(LATEST, "planted_cases.csv")
    rows = get_capacity_breaches.invoke({})
    assert {r["capacity_breach.ac_code"] for r in rows} == set(cases[cases.severity != "none"].ac_code)
    assert all(r["capacity_breach.severity"] != "none" for r in rows)
    quarters = [int(r["capacity_breach.quarters_to_breach"]) for r in rows]
    assert quarters == sorted(quarters)


def test_component_breach_returns_the_planted_severity():
    case = ground_truth(LATEST, "planted_cases.csv").query("case == 'baseline_only'").iloc[0]
    [row] = get_component_breach.invoke({"ac_code": case.ac_code})
    assert row["capacity_breach.severity"] == case.severity
    assert row["capacity_breach.recommended_action"]


def test_component_breach_of_unknown_component_is_empty():
    assert get_component_breach.invoke({"ac_code": "000000000"}) == []
