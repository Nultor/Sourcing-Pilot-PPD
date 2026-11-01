"""The saturation mart as the agents see it: through Cube, checked against the ground truth.

dbt already tests fct_saturation row by row (dbt/tests/). These tests check the layer on
top: Cube's measures, its snapshot filter and its sum/sum ratios, and that the numbers in
Cube are enough to reproduce every planted case's severity and first breach quarter.
Needs loaded data and Cube up (docker compose up -d); skips otherwise.
"""
from collections import defaultdict

import numpy as np
import pytest

from data_gen.saturation import classify
from semantic.cube_client import load
from tests.ground_truth import LATEST, SNAPSHOTS, ground_truth

TOLERANCE = 0.005   # same as the dbt ground-truth tests
pytestmark = pytest.mark.usefixtures("cube")
each_snapshot = pytest.mark.parametrize("snapshot", SNAPSHOTS)


def snapshot_filter(snapshot: str) -> dict:
    return {"member": "saturation_history.snapshot_quarter", "operator": "equals", "values": [snapshot]}


def test_saturation_cube_holds_only_the_latest_snapshot():
    rows = load({"dimensions": ["saturation.snapshot_quarter"]})
    assert [r["saturation.snapshot_quarter"] for r in rows] == [LATEST]


def test_saturation_history_holds_every_snapshot():
    rows = load({"dimensions": ["saturation_history.snapshot_quarter"],
                 "order": {"saturation_history.snapshot_quarter": "asc"}})
    assert [r["saturation_history.snapshot_quarter"] for r in rows] == SNAPSHOTS


@each_snapshot
def test_saturation_per_quarter_matches_ground_truth(snapshot):
    truth = ground_truth(snapshot, "saturation.csv").set_index(["ac_code", "quarter"])
    rows = load({
        "measures": ["saturation_history.baseline_saturation", "saturation_history.stretch_saturation"],
        "dimensions": ["saturation_history.ac_code", "saturation_history.forecast_quarter"],
        "filters": [snapshot_filter(snapshot)],
        "limit": 50000,
    })
    cube = {(r["saturation_history.ac_code"], r["saturation_history.forecast_quarter"]): r for r in rows}

    missing = sorted(set(truth.index) - set(cube))
    assert not missing, f"{len(missing)} component-quarters missing in Cube, e.g. {missing[:5]}"
    wrong = [
        key for key, t in truth.iterrows()
        if abs(float(cube[key]["saturation_history.baseline_saturation"]) - t.baseline_saturation) > TOLERANCE
        or abs(float(cube[key]["saturation_history.stretch_saturation"]) - t.stretch_saturation) > TOLERANCE
    ]
    assert not wrong, f"{len(wrong)} component-quarters off by more than {TOLERANCE}, e.g. {wrong[:5]}"


def test_saturation_over_several_quarters_is_total_demand_over_total_capacity():
    # pick the component where sum/sum and the average of the quarterly ratios differ most,
    # so this test fails if Cube ever averages ratios
    truth = ground_truth(LATEST, "saturation.csv")
    per_ac = truth.groupby("ac_code").agg(demand=("qty_baseline", "sum"), capacity=("baseline_capacity", "sum"),
                                          mean_ratio=("baseline_saturation", "mean"))
    per_ac["sum_over_sum"] = per_ac.demand / per_ac.capacity
    ac = (per_ac.sum_over_sum - per_ac.mean_ratio).abs().idxmax()

    rows = load({"measures": ["saturation.baseline_saturation"],
                 "filters": [{"member": "saturation.ac_code", "operator": "equals", "values": [ac]}]})
    assert float(rows[0]["saturation.baseline_saturation"]) == pytest.approx(per_ac.sum_over_sum[ac], abs=TOLERANCE)


@each_snapshot
def test_peaks_match_planted_cases(snapshot):
    cases = ground_truth(snapshot, "planted_cases.csv")
    rows = load({
        "measures": ["saturation_history.peak_baseline_saturation", "saturation_history.peak_stretch_saturation"],
        "dimensions": ["saturation_history.ac_code"],
        "filters": [snapshot_filter(snapshot)],
        "limit": 50000,
    })
    cube = {r["saturation_history.ac_code"]: r for r in rows}

    wrong = [
        c.ac_code for c in cases.itertuples()
        if c.ac_code not in cube
        or abs(float(cube[c.ac_code]["saturation_history.peak_baseline_saturation"]) - c.peak_baseline_saturation) > TOLERANCE
        or abs(float(cube[c.ac_code]["saturation_history.peak_stretch_saturation"]) - c.peak_stretch_saturation) > TOLERANCE
    ]
    assert not wrong, f"peaks wrong or missing for {wrong}"


@each_snapshot
def test_severity_and_first_breach_reproduce_from_cube(snapshot):
    """Applying the generator's rule (classify) to Cube's timelines gives the planted labels.

    This is what the agent is asked to do, so if it fails here the data is the problem,
    and if it passes here but the agent gets it wrong, the agent is."""
    cases = ground_truth(snapshot, "planted_cases.csv")
    rows = load({
        "measures": ["saturation_history.baseline_saturation", "saturation_history.stretch_saturation"],
        "dimensions": ["saturation_history.ac_code", "saturation_history.forecast_quarter"],
        "filters": [snapshot_filter(snapshot)],
        "order": {"saturation_history.forecast_quarter": "asc"},
        "limit": 50000,
    })
    timelines = defaultdict(list)
    for r in rows:
        timelines[r["saturation_history.ac_code"]].append(
            (r["saturation_history.forecast_quarter"],
             float(r["saturation_history.baseline_saturation"]),
             float(r["saturation_history.stretch_saturation"])))

    wrong = []
    for c in cases.itertuples():
        quarters, baseline, stretch = zip(*sorted(timelines[c.ac_code]))
        severity, first = classify(np.array(baseline), np.array(stretch))
        first_breach = quarters[first] if first is not None else None
        expected_first = c.first_breach_quarter if isinstance(c.first_breach_quarter, str) else None
        if (severity, first_breach) != (c.severity, expected_first):
            wrong.append((c.ac_code, c.case, (severity, first_breach), (c.severity, expected_first)))
    assert not wrong, f"(ac, case, from Cube, expected): {wrong}"
