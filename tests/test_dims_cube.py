"""The dimension marts (dim_component, dim_product, bridge_product_component) as the agents
see them: through the component / product / product_component cubes, vs the ground truth.

dbt already compares the marts with the truth (dbt/tests/assert_dim_*_matches_truth.sql).
These tests check the Cube layer on top: the latest-snapshot filter, the attributes, and
above all the joins: grouping saturation by a component attribute must not change totals
(a join without snapshot_quarter would double them).
Needs loaded data and Cube up (docker compose up -d); skips otherwise.
"""
import pandas as pd
import pytest

from semantic.cube_client import load
from tests.ground_truth import LATEST, SNAPSHOTS, ground_truth

pytestmark = pytest.mark.usefixtures("cube")


def text(value) -> str | None:
    """Ground-truth CSV blanks are NaN, Cube returns None: compare both as None."""
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)


def number(value) -> float | None:
    return None if text(value) is None else float(value)


def cube_rows(cube: str, key: str, fields: list[str], snapshot: str | None = None) -> dict[str, dict]:
    query = {"dimensions": [f"{cube}.{key}"] + [f"{cube}.{f}" for f in fields], "limit": 50000}
    if snapshot:
        query["filters"] = [{"member": f"{cube}.snapshot_quarter", "operator": "equals", "values": [snapshot]}]
    return {r[f"{cube}.{key}"]: {f: r[f"{cube}.{f}"] for f in fields} for r in load(query)}


def truth_usage(snapshot: str) -> pd.DataFrame:
    """n_products_using and used_by_hero per component, from the ground-truth BOM + products."""
    bom = ground_truth(snapshot, "bom.csv").astype({"pf_code": str})
    products = ground_truth(snapshot, "products.csv").astype({"pf_code": str})
    merged = bom.merge(products[["pf_code", "is_hero"]], on="pf_code")
    return merged.groupby("ac_code").agg(n_products_using=("pf_code", "nunique"), used_by_hero=("is_hero", "any"))


# --- component -----------------------------------------------------------------------

@pytest.mark.parametrize("cube", ["component", "product", "product_component"])
def test_latest_cubes_hold_only_the_latest_snapshot(cube):
    rows = load({"dimensions": [f"{cube}.snapshot_quarter"]})
    assert [r[f"{cube}.snapshot_quarter"] for r in rows] == [LATEST]


def test_component_cube_has_every_component_once():
    rows = load({"dimensions": ["component.ac_code"], "measures": ["component.count"], "limit": 50000})
    assert {r["component.ac_code"] for r in rows} == set(ground_truth(LATEST, "components.csv").ac_code)
    assert all(r["component.count"] == "1" for r in rows)


@pytest.mark.parametrize("snapshot", SNAPSHOTS)
def test_component_attributes_match_the_truth(snapshot):
    cube = cube_rows("component_history", "ac_code",
                     ["brand", "material", "size_ml", "is_new", "n_products_using", "used_by_hero"], snapshot)
    usage = truth_usage(snapshot)
    wrong = []
    for c in ground_truth(snapshot, "components.csv").itertuples():
        r = cube.get(c.ac_code)
        if (r is None
                or text(r["brand"]) != text(c.brand)
                or text(r["material"]) != text(c.material)
                or number(r["size_ml"]) != number(c.size_ml)
                or r["is_new"] != bool(c.is_new)
                or int(r["n_products_using"]) != int(usage.n_products_using.get(c.ac_code, 0))
                or r["used_by_hero"] != bool(usage.used_by_hero.get(c.ac_code, False))):
            wrong.append(c.ac_code)
    assert not wrong, f"components wrong or missing: {wrong}"


# --- product -------------------------------------------------------------------------

@pytest.mark.parametrize("snapshot", SNAPSHOTS)
def test_product_attributes_match_the_truth(snapshot):
    cube = cube_rows("product_history", "pf_code",
                     ["brand", "format_ml", "is_hero", "is_npd", "launch_quarter"], snapshot)
    truth = ground_truth(snapshot, "products.csv").astype({"pf_code": str})
    assert set(cube) == set(truth.pf_code)
    wrong = [p.pf_code for p in truth.itertuples()
             if (cube[p.pf_code]["brand"] != p.brand
                 or number(cube[p.pf_code]["format_ml"]) != number(p.format_ml)
                 or cube[p.pf_code]["is_hero"] != bool(p.is_hero)
                 or cube[p.pf_code]["is_npd"] != bool(p.is_npd)
                 or text(cube[p.pf_code]["launch_quarter"]) != text(p.launch_quarter))]
    assert not wrong, f"products wrong: {wrong}"


def test_product_component_is_the_truth_bom():
    rows = load({"dimensions": ["product_component.pf_code", "product_component.ac_code"], "limit": 50000})
    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    assert {(r["product_component.pf_code"], r["product_component.ac_code"]) for r in rows} == \
        set(zip(bom.pf_code, bom.ac_code))


# --- joins ---------------------------------------------------------------------------

@pytest.mark.parametrize("dimension", ["component.family", "component.used_by_hero", "component.material"])
def test_grouping_saturation_by_a_component_attribute_keeps_the_total(dimension):
    total = float(load({"measures": ["saturation.forecast_demand_baseline"]})[0]["saturation.forecast_demand_baseline"])
    groups = load({"measures": ["saturation.forecast_demand_baseline"], "dimensions": [dimension], "limit": 50000})
    assert sum(float(r["saturation.forecast_demand_baseline"]) for r in groups) == pytest.approx(total)


def test_history_join_keeps_each_snapshot_total():
    def per_snapshot(dimensions):
        rows = load({"measures": ["saturation_history.baseline_capacity"],
                     "dimensions": ["saturation_history.snapshot_quarter"] + dimensions, "limit": 50000})
        totals: dict[str, float] = {}
        for r in rows:
            snapshot = r["saturation_history.snapshot_quarter"]
            totals[snapshot] = totals.get(snapshot, 0) + float(r["saturation_history.baseline_capacity"])
        return totals

    assert per_snapshot(["component_history.family"]) == pytest.approx(per_snapshot([]))


def test_breach_cube_joins_one_component_per_row():
    rows = load({"dimensions": ["capacity_breach.ac_code", "component.family"],
                 "measures": ["capacity_breach.component_count"], "limit": 50000})
    alone = load({"dimensions": ["capacity_breach.ac_code"], "limit": 50000})   # only ACs with capacity data
    assert len(rows) == len(alone)
    assert all(r["capacity_breach.component_count"] == "1" and r["component.family"] for r in rows)
