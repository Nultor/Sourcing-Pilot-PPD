"""The agent's Cube tools (pipeline/tools/cube.py) on the saturation and breach marts.

Checks that each named tool runs the query it promises, and that the generic fallback
rejects names Cube doesn't know. Needs loaded data and Cube up; skips otherwise.
"""
import pandas as pd
import pytest
from pydantic import ValidationError

from pipeline.tools.cube import (compare_snapshots, get_capacity_breaches, get_component_breach,
                                 get_component_info, get_component_timeline, get_product_volume_at_risk,
                                 get_products_at_risk, get_top_saturated, get_total_volume_at_risk,
                                 get_volume_at_risk, list_metrics, query_metric)
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
    assert {"saturation", "saturation_history", "component", "product", "product_component"} <= set(cubes)
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


def test_capacity_breaches_say_what_the_component_is():
    components = ground_truth(LATEST, "components.csv").set_index("ac_code")
    for r in get_capacity_breaches.invoke({}):
        assert r["component.description"] == components.loc[r["capacity_breach.ac_code"], "description"]
        assert r["component.family"]
        assert isinstance(r["component.used_by_hero"], bool)


# --- component and product tools ------------------------------------------------------

def truth_bom() -> pd.DataFrame:
    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    products = ground_truth(LATEST, "products.csv").astype({"pf_code": str})
    return bom.merge(products, on="pf_code")


def test_component_info_lists_the_component_and_every_product_using_it():
    bom = truth_bom()
    ac = bom.ac_code.value_counts().index[0]            # the most shared component
    info = get_component_info.invoke({"ac_code": ac})
    truth = ground_truth(LATEST, "components.csv").set_index("ac_code").loc[ac]

    assert info["component"]["component.description"] == truth.description
    assert int(info["component"]["component.n_products_using"]) == len(bom[bom.ac_code == ac])
    products = {p["product_component.pf_code"]: p for p in info["products"]}
    assert set(products) == set(bom[bom.ac_code == ac].pf_code)
    for row in bom[bom.ac_code == ac].itertuples():
        assert products[row.pf_code]["product.is_hero"] == bool(row.is_hero)


def test_component_info_of_unknown_component_is_empty():
    assert get_component_info.invoke({"ac_code": "000000000"}) == {"component": {}, "products": []}


def products_hit(severities: list[str], hero_only: bool = False) -> set[tuple[str, str]]:
    cases = ground_truth(LATEST, "planted_cases.csv")
    bom = truth_bom().merge(cases[["ac_code", "severity"]], on="ac_code")
    hit = bom[bom.severity.isin(severities) & (bom.is_hero | (not hero_only))]
    return set(zip(hit.pf_code, hit.ac_code))


def pairs(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["product_component.pf_code"], r["product_component.ac_code"]) for r in rows}


def test_products_at_risk_default_is_every_product_on_a_real_breach():
    rows = get_products_at_risk.invoke({})
    assert pairs(rows) == products_hit(["high", "medium", "early_warning"])
    breach_quarters = [int(r["capacity_breach.quarters_to_breach"]) for r in rows]
    assert breach_quarters == sorted(breach_quarters)


def test_products_at_risk_filters_heroes_and_severity():
    rows = get_products_at_risk.invoke({"severities": ["high"], "hero_only": True})
    assert rows and all(r["product.is_hero"] and r["capacity_breach.severity"] == "high" for r in rows)
    assert pairs(rows) == products_hit(["high"], hero_only=True)


def test_products_at_risk_only_accepts_known_severities():
    with pytest.raises(ValidationError):
        get_products_at_risk.invoke({"severities": ["catastrophic"]})


# --- volume and value at risk ---------------------------------------------------------

def revenue(row: dict, cube: str) -> float:
    value = row[f"{cube}.revenue_at_risk_baseline"]
    return -1 if value is None else float(value)


def test_volume_at_risk_lists_components_worst_first_and_only_real_breaches():
    rows = get_volume_at_risk.invoke({})
    values = [revenue(r, "volume_at_risk") for r in rows]
    assert rows and values == sorted(values, reverse=True)
    assert all(float(r["volume_at_risk.units_at_risk_stretch"]) > 0 for r in rows)
    assert all(r["capacity_breach.severity"] != "none" for r in rows)


def test_volume_at_risk_of_one_component_splits_over_its_products():
    worst = get_volume_at_risk.invoke({})[0]
    ac = worst["volume_at_risk.ac_code"]
    result = get_volume_at_risk.invoke({"ac_code": ac})
    split = result["per_product"]
    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    assert {r["volume_at_risk.pf_code"] for r in split} <= set(bom[bom.ac_code == ac].pf_code)
    assert float(result["total"]["volume_at_risk.revenue_at_risk_baseline"]) == \
        pytest.approx(float(worst["volume_at_risk.revenue_at_risk_baseline"]), abs=1)
    assert sum(revenue(r, "volume_at_risk") for r in split if r["volume_at_risk.revenue_at_risk_baseline"]) == \
        pytest.approx(float(worst["volume_at_risk.revenue_at_risk_baseline"]), abs=1)


def test_volume_at_risk_of_a_component_without_loss_has_no_products():
    result = get_volume_at_risk.invoke({"ac_code": "000000000"})
    assert result == {"total": {}, "per_product": []}


def test_product_volume_at_risk_heroes_and_one_product_by_quarter():
    rows = get_product_volume_at_risk.invoke({"hero_only": True})
    assert rows and all(r["product.is_hero"] for r in rows)
    values = [revenue(r, "product_volume_at_risk") for r in rows]
    assert values == sorted(values, reverse=True)

    pf = rows[0]["product_volume_at_risk.pf_code"]
    result = get_product_volume_at_risk.invoke({"pf_code": pf})
    assert float(result["total"]["product_volume_at_risk.revenue_at_risk_baseline"]) == \
        pytest.approx(revenue(rows[0], "product_volume_at_risk"), abs=1)
    quarters = result["per_quarter"]
    names = [q["product_volume_at_risk.forecast_quarter"] for q in quarters]
    assert names == sorted(names)
    assert sum(float(q["product_volume_at_risk.units_at_risk_stretch"]) for q in quarters) == \
        pytest.approx(float(rows[0]["product_volume_at_risk.units_at_risk_stretch"]), abs=0.01)


def test_total_volume_at_risk_is_the_sum_of_its_years_and_products():
    result = get_total_volume_at_risk.invoke({})
    total = result["total"]
    for measure in ["units_at_risk_baseline", "revenue_at_risk_baseline", "revenue_at_risk_stretch"]:
        key = f"product_volume_at_risk.{measure}"
        assert sum(float(y[key]) for y in result["per_year"]) == pytest.approx(float(total[key]), abs=1)
    products = get_product_volume_at_risk.invoke({})
    assert int(total["product_volume_at_risk.products_at_risk_stretch"]) == len(products)
