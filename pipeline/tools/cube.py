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
    Filter example: [{"member": "saturation.ac_code", "operator": "equals", "values": ["366413968"]}]
    """
    known = {m["name"] for cube in get_meta()["cubes"] for m in cube["measures"] + cube["dimensions"]}
    used = measures + (dimensions or []) + [f["member"] for f in filters or []] + list(order or {})
    unknown = [name for name in used if name not in known]
    if unknown:
        return f"Unknown names: {unknown}. Call list_metrics to see the valid ones."

    query = {"measures": measures, "dimensions": dimensions, "filters": filters, "order": order, "limit": limit}
    return load({key: value for key, value in query.items() if value})


CUBE_TOOLS = [get_top_saturated, get_component_timeline, compare_snapshots, list_metrics, query_metric]


if __name__ == "__main__":
    print(get_top_saturated.invoke({"limit": 3}), "\n")
    print(get_component_timeline.invoke({"ac_code": "366413968"}), "\n")
    print(compare_snapshots.invoke({"ac_code": "369576663"}), "\n")
    print(query_metric.invoke({"measures": ["saturation.wrong_name"]}))   # should print "Unknown names"
