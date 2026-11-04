"""The volume-at-risk marts (fct_volume_at_risk, fct_product_volume_at_risk) through Cube,
vs an independent recalculation from the ground truth (saturation.csv, forecast.csv, bom.csv).

The recalculation follows the rules in TODO.md item 2: shortfall = demand - baseline capacity
(no CMs), split over products by their share of the component's demand; a product loses the
largest share over its components. Baseline units must match closely; stretch allows 1%
because staging estimates a few blank stretch forecasts. Euros can't be checked against the
truth (it has no net sales), so they are checked for consistency: units x price.
Needs loaded data and Cube up (docker compose up -d); skips otherwise.
"""
import pandas as pd
import pytest

from semantic.cube_client import load
from tests.ground_truth import LATEST, ground_truth

pytestmark = pytest.mark.usefixtures("cube")


@pytest.fixture(scope="module")
def truth() -> pd.DataFrame:
    """Units at risk per AC x PF x quarter, recalculated from the ground truth."""
    sat = ground_truth(LATEST, "saturation.csv")
    forecast = ground_truth(LATEST, "forecast.csv").astype({"pf_code": str})
    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    sat["short_b"] = (sat.qty_baseline - sat.baseline_capacity).clip(lower=0)
    sat["short_s"] = (sat.qty_stretch - sat.baseline_capacity).clip(lower=0)
    rows = (bom.merge(forecast, on="pf_code")
               .merge(sat[["ac_code", "quarter", "qty_baseline", "qty_stretch", "short_b", "short_s"]],
                      on=["ac_code", "quarter"], suffixes=("_pf", "_ac")))
    rows["units_b"] = rows.qty_baseline_pf * rows.short_b / rows.qty_baseline_ac
    rows["units_s"] = rows.qty_stretch_pf * rows.short_s / rows.qty_stretch_ac
    return rows


def per(cube: str, dimension: str) -> pd.DataFrame:
    rows = load({"dimensions": [f"{cube}.{dimension}"],
                 "measures": [f"{cube}.units_at_risk_baseline", f"{cube}.units_at_risk_stretch"], "limit": 50000})
    return pd.DataFrame({
        dimension: [r[f"{cube}.{dimension}"] for r in rows],
        "units_b": [float(r[f"{cube}.units_at_risk_baseline"]) for r in rows],
        "units_s": [float(r[f"{cube}.units_at_risk_stretch"]) for r in rows],
    }).set_index(dimension)


@pytest.mark.parametrize("cube", ["volume_at_risk", "product_volume_at_risk"])
def test_cubes_hold_only_the_latest_snapshot(cube):
    rows = load({"dimensions": [f"{cube}.snapshot_quarter"]})
    assert [r[f"{cube}.snapshot_quarter"] for r in rows] == [LATEST]


def test_planted_case_shortfall_is_split_over_its_products(truth):
    # AC 366413968 is short 119,810 pieces in 2029Q4 (snapshot 2026Q4, see TODO.md)
    case = truth[(truth.ac_code == "366413968") & (truth.quarter == "2029Q4")]
    if LATEST == "2026Q4":
        assert case.short_b.iloc[0] == 119_810
    rows = load({"measures": ["volume_at_risk.units_at_risk_baseline"],
                 "filters": [{"member": "volume_at_risk.ac_code", "operator": "equals", "values": ["366413968"]},
                             {"member": "volume_at_risk.forecast_quarter", "operator": "equals", "values": ["2029Q4"]}]})
    assert float(rows[0]["volume_at_risk.units_at_risk_baseline"]) == pytest.approx((case.units_b * case.qty_per_pf).sum(), abs=0.01)


def test_units_at_risk_per_component_match_the_truth(truth):
    expected = truth.groupby("ac_code")[["units_b", "units_s"]].sum()
    expected = expected[expected.units_s > 0]
    cube = per("volume_at_risk", "ac_code").reindex(expected.index)
    assert cube.units_b.values == pytest.approx(expected.units_b.values, abs=0.01)
    assert cube.units_s.values == pytest.approx(expected.units_s.values, rel=0.01)


def test_a_product_loses_its_largest_component_share_not_the_sum(truth):
    expected = (truth.groupby(["pf_code", "quarter"])[["units_b", "units_s"]].max()
                     .groupby("pf_code").sum())
    expected = expected[expected.units_s > 0]
    cube = per("product_volume_at_risk", "pf_code").reindex(expected.index)
    assert cube.units_b.values == pytest.approx(expected.units_b.values, abs=0.01)
    assert cube.units_s.values == pytest.approx(expected.units_s.values, rel=0.01)

    summed = truth.groupby("pf_code").units_b.sum()
    assert summed.sum() > expected.units_b.sum()     # summing over components would overstate


def test_revenue_is_units_times_price_and_launches_have_none():
    rows = load({"dimensions": ["product_volume_at_risk.pf_code", "product_volume_at_risk.price_eur_per_unit",
                                "product_volume_at_risk.has_price", "product.is_npd"],
                 "measures": ["product_volume_at_risk.units_at_risk_stretch",
                              "product_volume_at_risk.revenue_at_risk_stretch",
                              "product_volume_at_risk.units_without_price_stretch"],
                 "limit": 50000})
    for r in rows:
        units = float(r["product_volume_at_risk.units_at_risk_stretch"])
        revenue = r["product_volume_at_risk.revenue_at_risk_stretch"]
        if r["product_volume_at_risk.has_price"]:
            assert float(revenue) == pytest.approx(units * float(r["product_volume_at_risk.price_eur_per_unit"]), abs=1)
            assert float(r["product_volume_at_risk.units_without_price_stretch"]) == 0
        else:
            assert r["product.is_npd"] and revenue is None
            assert float(r["product_volume_at_risk.units_without_price_stretch"]) == pytest.approx(units)


def test_contribution_is_below_revenue():
    r = load({"measures": ["product_volume_at_risk.revenue_at_risk_baseline",
                           "product_volume_at_risk.contribution_at_risk_baseline"]})[0]
    revenue = float(r["product_volume_at_risk.revenue_at_risk_baseline"])
    assert 0 < float(r["product_volume_at_risk.contribution_at_risk_baseline"]) < revenue


def test_joins_keep_the_total():
    total = float(load({"measures": ["volume_at_risk.units_at_risk_baseline"]})[0]["volume_at_risk.units_at_risk_baseline"])
    for dimension in ["component.family", "product.is_hero", "capacity_breach.severity"]:
        groups = load({"measures": ["volume_at_risk.units_at_risk_baseline"], "dimensions": [dimension], "limit": 5000})
        assert sum(float(g["volume_at_risk.units_at_risk_baseline"]) for g in groups) == pytest.approx(total)
