"""Tools the agents use to read the semantic layer (Cube).

Named tools answer the common questions with a fixed query, so the same question always
runs the same query. query_metric is the fallback for anything else.

Quick check against the running Cube (from the repo root):
    python -m pipeline.tools.cube
"""
from typing import Literal

from langchain_core.tools import tool

from semantic.cube_client import get_meta, load


# --- Named tools: fixed queries, the LLM only picks the parameters -------------------

@tool
def get_top_saturated(scenario: Literal["baseline", "stretch"] = "stretch", limit: int = 10) -> list[dict]:
    """Most saturated components (AC) in the latest snapshot, worst first.

    Returns ac_code with peak (worst single-quarter) baseline and stretch saturation.
    scenario chooses which peak to sort by. Above 0.85 is a warning, above 1.0 critical.
    """
    return load({
        "measures": ["saturation.peak_baseline_saturation", "saturation.peak_stretch_saturation"],
        "dimensions": ["saturation.ac_code"],
        "order": {f"saturation.peak_{scenario}_saturation": "desc"},
        "limit": limit,
    })


@tool
def get_component_timeline(ac_code: str) -> list[dict]:
    """One component (AC) quarter by quarter in the latest snapshot: demand, capacity,
    baseline and stretch saturation. Use it to find the first quarter above a threshold."""
    return load({
        "measures": [
            "saturation.forecast_demand_baseline",
            "saturation.forecast_demand_stretch",
            "saturation.baseline_capacity",
            "saturation.stretch_capacity",
            "saturation.baseline_saturation",
            "saturation.stretch_saturation",
        ],
        "dimensions": ["saturation.forecast_quarter"],
        "filters": [{"member": "saturation.ac_code", "operator": "equals", "values": [ac_code]}],
        "order": {"saturation.forecast_quarter": "asc"},
    })


@tool
def compare_snapshots(ac_code: str) -> list[dict]:
    """One component (AC) across data snapshots (e.g. 2026Q3 vs 2026Q4): peak baseline and
    stretch saturation per snapshot. Use it to see if the situation got better or worse."""
    return load({
        "measures": ["saturation_history.peak_baseline_saturation", "saturation_history.peak_stretch_saturation"],
        "dimensions": ["saturation_history.snapshot_quarter"],
        "filters": [{"member": "saturation_history.ac_code", "operator": "equals", "values": [ac_code]}],
        "order": {"saturation_history.snapshot_quarter": "asc"},
    })


BREACH_FIELDS = [
    "capacity_breach.ac_code",
    "capacity_breach.severity",
    "capacity_breach.recommended_action",
    "capacity_breach.first_breach_quarter",
    "capacity_breach.quarters_to_breach",
    "capacity_breach.first_critical_quarter",
    "capacity_breach.n_quarters_baseline_over",
    "capacity_breach.n_quarters_stretch_over",
]
# what the component is, joined from the component cube (dbt dim_component)
COMPONENT_FIELDS = [
    "component.description",
    "component.family",
    "component.used_by_hero",
    "component.n_products_using",
]
BREACH_MEASURES = [
    "capacity_breach.peak_baseline_saturation",
    "capacity_breach.peak_stretch_saturation",
    "capacity_breach.peak_baseline_shortfall",
    "capacity_breach.peak_stretch_shortfall",
]


@tool
def get_capacity_breaches() -> list[dict]:
    """Every component (AC) with a capacity problem in the latest snapshot, soonest breach first.
    Includes what the component is (description, family) and whether a hero product uses it.

    Severity, first breach quarter, quarters to breach, recommended action and worst shortfall
    are already calculated (dbt); use them as they are. Components without a problem
    (severity none) are left out. Use this for "which components breach / need action".
    """
    return load({
        "dimensions": BREACH_FIELDS + COMPONENT_FIELDS,
        "measures": BREACH_MEASURES,
        "filters": [{"member": "capacity_breach.severity", "operator": "notEquals", "values": ["none"]}],
        "order": {"capacity_breach.quarters_to_breach": "asc", "capacity_breach.peak_baseline_saturation": "desc"},
    })


@tool
def get_component_breach(ac_code: str) -> list[dict]:
    """Breach summary of one component (AC) in the latest snapshot: severity, recommended action,
    first breach quarter, quarters to breach, quarters over threshold, worst shortfall.
    Already calculated (dbt); use it as it is. Empty if the component is unknown."""
    return load({
        "dimensions": BREACH_FIELDS + COMPONENT_FIELDS,
        "measures": BREACH_MEASURES,
        "filters": [{"member": "capacity_breach.ac_code", "operator": "equals", "values": [ac_code]}],
    })


# --- Components and products: what things are, and who is hit by a breach ------------

COMPONENT_INFO = [
    "component.ac_code", "component.description", "component.family", "component.material",
    "component.size_ml", "component.neck", "component.colour", "component.weight_g",
    "component.technology", "component.brand", "component.status", "component.is_new",
    "component.n_products_using", "component.used_by_hero",
]
PRODUCT_FIELDS = [
    "product_component.pf_code", "product.description", "product.brand", "product.format_ml",
    "product.is_hero", "product.is_npd", "product.launch_quarter",
]


@tool
def get_component_info(ac_code: str) -> dict:
    """What one component (AC) is in the latest snapshot: description, family, material, size,
    brand (empty = generic, used across brands), whether it is new for a launch, and every
    product (PF) that uses it with the product's brand, hero flag and launch status.
    Empty component if the AC is unknown."""
    component = load({
        "dimensions": COMPONENT_INFO,
        "filters": [{"member": "component.ac_code", "operator": "equals", "values": [ac_code]}],
    })
    products = load({
        "dimensions": PRODUCT_FIELDS + ["product_component.qty_per_pf"],
        "filters": [{"member": "product_component.ac_code", "operator": "equals", "values": [ac_code]}],
        "order": {"product.is_hero": "desc", "product_component.pf_code": "asc"},
    })
    return {"component": component[0] if component else {}, "products": products}


@tool
def get_products_at_risk(
    severities: list[Literal["high", "medium", "early_warning", "temporary_spike"]] | None = None,
    hero_only: bool = False,
) -> list[dict]:
    """Products (PF) that use a component with a capacity problem in the latest snapshot: one
    row per product x problem component, with the product (brand, hero, launch) and the
    component's severity, first breach quarter and recommended action, soonest breach first.

    severities: which severities count (default high, medium and early_warning; a
    temporary_spike is a one-off and usually not a risk). hero_only: only hero products.
    Use this for "which products / hero products are affected by capacity problems"."""
    filters = [{"member": "capacity_breach.severity", "operator": "equals",
                "values": severities or ["high", "medium", "early_warning"]}]
    if hero_only:
        filters.append({"member": "product.is_hero", "operator": "equals", "values": ["true"]})
    return load({
        "dimensions": PRODUCT_FIELDS + [
            "product_component.ac_code", "component.description",
            "capacity_breach.severity", "capacity_breach.first_breach_quarter",
            "capacity_breach.quarters_to_breach", "capacity_breach.recommended_action",
        ],
        "filters": filters,
        "order": {"capacity_breach.quarters_to_breach": "asc", "product_component.pf_code": "asc"},
        "limit": 1000,
    })


# --- Volume and value at risk: what a shortfall costs, without CMs or investment -------

def _measures(cube: str) -> list[str]:
    return [f"{cube}.{m}_{scenario}" for m in
            ("units_at_risk", "revenue_at_risk", "contribution_at_risk", "units_without_price")
            for scenario in ("baseline", "stretch")]


def _worst_first(rows: list[dict], revenue: str) -> list[dict]:
    """Sort by revenue at risk, highest first. Rows without a price (launches) go last
    (Postgres would put the nulls first)."""
    return sorted(rows, key=lambda r: float(r[revenue]) if r[revenue] is not None else -1, reverse=True)


@tool
def get_volume_at_risk(ac_code: str | None = None) -> list[dict] | dict:
    """What component shortfalls cost if we DON'T use CMs or invest, latest snapshot, over the
    3-year forecast horizon, for the baseline and the stretch forecast.

    Without ac_code: one row per component that causes a loss, highest revenue at risk first,
    with its severity. With ac_code: {"total": that component's total, "per_product": its loss
    split over the products using it, with hero flag}. Use "total" for the component's figure.
    Units = product units that can't be made. Revenue = units x selling price. Contribution =
    units x (price - packaging cost), before all other costs. units_without_price = units of
    launches without a price, not included in the euros. Don't add components up per product
    (double counts): for products and totals use get_product_volume_at_risk / get_total_volume_at_risk.
    """
    real_loss = {"member": "volume_at_risk.units_at_risk_stretch", "operator": "gt", "values": ["0"]}
    if ac_code is None:
        rows = load({
            "dimensions": ["volume_at_risk.ac_code", "component.description", "capacity_breach.severity",
                           "capacity_breach.first_breach_quarter"],
            "measures": _measures("volume_at_risk"),
            "filters": [real_loss],
            "limit": 1000,
        })
        return _worst_first(rows, "volume_at_risk.revenue_at_risk_baseline")

    this_component = {"member": "volume_at_risk.ac_code", "operator": "equals", "values": [ac_code]}
    total = load({"dimensions": ["volume_at_risk.ac_code", "component.description"],
                  "measures": _measures("volume_at_risk"), "filters": [this_component]})
    per_product = load({
        "dimensions": ["volume_at_risk.pf_code", "product.description", "product.is_hero", "product.is_npd"],
        "measures": _measures("volume_at_risk"),
        "filters": [this_component, real_loss],
        "limit": 1000,
    })
    return {"total": total[0] if total else {},
            "per_product": _worst_first(per_product, "volume_at_risk.revenue_at_risk_baseline")}


@tool
def get_product_volume_at_risk(pf_code: str | None = None, hero_only: bool = False) -> list[dict] | dict:
    """Products (PF) that lose units if we DON'T use CMs or invest, latest snapshot, baseline and
    stretch forecast, over the 3-year horizon. A product short on several components loses the
    largest share, not the sum.

    Without pf_code (use this for rankings, "which product loses most"): one row per product
    losing units, already sorted highest revenue at risk first, with hero flag and the share of
    its forecast at risk. hero_only: only heroes.
    With pf_code: {"total": that product's total over the horizon, "per_quarter": quarter by
    quarter with the component that limits it (binding_ac_code)}. Use "total" for its figure.
    Revenue / contribution as in get_volume_at_risk; launches have no price.
    """
    filters = [{"member": "product_volume_at_risk.units_at_risk_stretch", "operator": "gt", "values": ["0"]}]
    if hero_only:
        filters.append({"member": "product.is_hero", "operator": "equals", "values": ["true"]})
    measures = _measures("product_volume_at_risk") + [
        "product_volume_at_risk.share_at_risk_baseline", "product_volume_at_risk.share_at_risk_stretch"]
    product = ["product_volume_at_risk.pf_code", "product.description", "product.brand",
               "product.is_hero", "product.is_npd"]
    if pf_code is None:
        rows = load({"dimensions": product, "measures": measures, "filters": filters, "limit": 1000})
        return _worst_first(rows, "product_volume_at_risk.revenue_at_risk_baseline")

    this_product = {"member": "product_volume_at_risk.pf_code", "operator": "equals", "values": [pf_code]}
    total = load({"dimensions": product, "measures": measures, "filters": [this_product]})
    per_quarter = load({
        "dimensions": ["product_volume_at_risk.forecast_quarter", "product_volume_at_risk.binding_ac_code_baseline",
                       "product_volume_at_risk.binding_ac_code_stretch"],
        "measures": measures,
        "filters": filters + [this_product],
        "order": {"product_volume_at_risk.forecast_quarter": "asc"},
    })
    return {"total": total[0] if total else {}, "per_quarter": per_quarter}


@tool
def get_total_volume_at_risk() -> dict:
    """The total answer to "if we don't invest and don't use CMs, how many products can't we
    make and what is that worth?", latest snapshot, baseline and stretch forecast: per forecast
    year and over the whole 3-year horizon. Number of products affected, units, revenue,
    contribution (price - packaging cost, before other costs), units of launches without a
    price (not in the euros), and the share of the forecast of the affected products."""
    measures = _measures("product_volume_at_risk") + [
        "product_volume_at_risk.products_at_risk_baseline", "product_volume_at_risk.products_at_risk_stretch"]
    total = load({"measures": measures})
    per_year = load({
        "dimensions": ["product_volume_at_risk.forecast_year"],
        "measures": measures,
        "order": {"product_volume_at_risk.forecast_year": "asc"},
    })
    return {"total": total[0] if total else {}, "per_year": per_year}


# --- Generic fallback: for questions no named tool covers ----------------------------

@tool
def list_metrics() -> list[dict]:
    """All cubes with their measures and dimensions and what each one means.
    Call this before query_metric to find valid names."""
    return [
        {
            "cube": cube["name"],
            "description": cube.get("description", ""),
            "measures": {m["name"]: m.get("description", "") for m in cube["measures"] if m.get("isVisible", True)},
            "dimensions": {d["name"]: d.get("description", "") for d in cube["dimensions"] if d.get("isVisible", True)},
        }
        for cube in get_meta()["cubes"]
    ]


@tool
def query_metric(
    measures: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict] | None = None,
    order: dict[str, str] | None = None,
    limit: int = 100,
) -> list[dict] | str:
    """Fallback: run any Cube query when no named tool fits.

    Names are cube.member, as listed by list_metrics. Use the 'saturation' cube for the
    latest snapshot; use 'saturation_history' only to compare snapshots, and then always
    group or filter by saturation_history.snapshot_quarter.
    saturation and capacity_breach join to 'component', so component.* dimensions can be
    used with their measures (e.g. saturation grouped by component.family). Products are
    reached through 'product_component' (product_component -> product, component, capacity_breach).
    Filter example: [{"member": "saturation.ac_code", "operator": "equals", "values": ["366413968"]}]
    """
    known = {m["name"] for cube in get_meta()["cubes"] for m in cube["measures"] + cube["dimensions"]}
    used = measures + (dimensions or []) + [f["member"] for f in filters or []] + list(order or {})
    unknown = [name for name in used if name not in known]
    if unknown:
        return f"Unknown names: {unknown}. Call list_metrics to see the valid ones."

    query = {"measures": measures, "dimensions": dimensions, "filters": filters, "order": order, "limit": limit}
    return load({key: value for key, value in query.items() if value})


CUBE_TOOLS = [get_capacity_breaches, get_component_breach, get_top_saturated, get_component_timeline,
              compare_snapshots, get_component_info, get_products_at_risk, get_total_volume_at_risk,
              get_volume_at_risk, get_product_volume_at_risk, list_metrics, query_metric]


if __name__ == "__main__":
    print(get_top_saturated.invoke({"limit": 3}), "\n")
    print(get_component_timeline.invoke({"ac_code": "366413968"}), "\n")
    print(compare_snapshots.invoke({"ac_code": "369576663"}), "\n")
    print(get_capacity_breaches.invoke({})[:2], "\n")
    print(get_component_breach.invoke({"ac_code": "362419787"}), "\n")
    print(get_component_info.invoke({"ac_code": "368875649"}), "\n")
    print(get_products_at_risk.invoke({"hero_only": True})[:2], "\n")
    print(get_total_volume_at_risk.invoke({}), "\n")
    print(get_volume_at_risk.invoke({})[:2], "\n")
    print(get_product_volume_at_risk.invoke({"hero_only": True})[:2], "\n")
    print(query_metric.invoke({"measures": ["saturation.wrong_name"]}))   # should print "Unknown names"
