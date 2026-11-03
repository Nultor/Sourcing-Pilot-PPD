"""The breach mart (fct_quarters_to_breach) as the agents see it: through Cube, vs the ground truth.

dbt already checks severity and first breach against planted_cases.csv
(dbt/tests/assert_breach_matches_planted_cases.sql). These tests check the layer on top:
the cubes, their snapshot filter, and that the breach summary agrees with the saturation cube.
Needs loaded data and Cube up (docker compose up -d); skips otherwise.
"""
import pandas as pd
import pytest

from semantic.cube_client import load
from tests.ground_truth import LATEST, SNAPSHOTS, ground_truth

TOLERANCE = 0.005
pytestmark = pytest.mark.usefixtures("cube")


def breaches(snapshot: str) -> dict[str, dict]:
    rows = load({
        "dimensions": ["capacity_breach_history.ac_code", "capacity_breach_history.severity",
                       "capacity_breach_history.first_breach_quarter", "capacity_breach_history.quarters_to_breach"],
        "measures": ["capacity_breach_history.peak_baseline_saturation",
                     "capacity_breach_history.peak_stretch_saturation"],
        "filters": [{"member": "capacity_breach_history.snapshot_quarter", "operator": "equals",
                     "values": [snapshot]}],
        "limit": 50000,
    })
    return {r["capacity_breach_history.ac_code"]: r for r in rows}


def test_capacity_breach_cube_holds_only_the_latest_snapshot():
    rows = load({"dimensions": ["capacity_breach.snapshot_quarter"]})
    assert [r["capacity_breach.snapshot_quarter"] for r in rows] == [LATEST]


def test_one_row_per_component():
    rows = load({"dimensions": ["capacity_breach.ac_code"], "measures": ["capacity_breach.component_count"],
                 "limit": 50000})
    assert all(r["capacity_breach.component_count"] == "1" for r in rows)


@pytest.mark.parametrize("snapshot", SNAPSHOTS)
def test_severity_first_breach_and_peaks_match_planted_cases(snapshot):
    cube = breaches(snapshot)
    wrong = []
    for c in ground_truth(snapshot, "planted_cases.csv").itertuples():
        r = cube.get(c.ac_code)
        expected_first = None if pd.isna(c.first_breach_quarter) else c.first_breach_quarter
        if (r is None
                or r["capacity_breach_history.severity"] != c.severity
                or r["capacity_breach_history.first_breach_quarter"] != expected_first
                or abs(float(r["capacity_breach_history.peak_baseline_saturation"]) - c.peak_baseline_saturation) > TOLERANCE
                or abs(float(r["capacity_breach_history.peak_stretch_saturation"]) - c.peak_stretch_saturation) > TOLERANCE):
            wrong.append((c.ac_code, c.case))
    assert not wrong, f"(ac, case) wrong or missing: {wrong}"


def test_quarters_to_breach_counts_from_the_snapshot():
    # the first forecast quarter is the quarter after the snapshot, so it is 1 quarter away
    year, quarter = int(LATEST[:4]), int(LATEST[-1])
    next_quarter = f"{year + quarter // 4}Q{quarter % 4 + 1}"
    for r in breaches(LATEST).values():
        if r["capacity_breach_history.first_breach_quarter"] == next_quarter:
            assert r["capacity_breach_history.quarters_to_breach"] == "1"


def test_breach_peaks_agree_with_the_saturation_cube():
    saturation = {
        r["saturation.ac_code"]: r for r in load({
            "dimensions": ["saturation.ac_code"],
            "measures": ["saturation.peak_baseline_saturation", "saturation.peak_stretch_saturation"],
            "limit": 50000,
        })
    }
    breach = breaches(LATEST)
    assert set(breach) == set(saturation)
    for ac, r in breach.items():
        assert float(r["capacity_breach_history.peak_baseline_saturation"]) == pytest.approx(
            float(saturation[ac]["saturation.peak_baseline_saturation"]), abs=1e-6)
