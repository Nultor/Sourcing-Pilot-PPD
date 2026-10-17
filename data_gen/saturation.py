"""Capacity world and planted saturation cases.

Definitions (see README §3.1):
  baseline capacity   = lines in use today (own plant + current suppliers), without CMs
  stretch capacity    = baseline capacity + CM capacity available today and qualified
  baseline saturation = QTY baseline / baseline capacity
  stretch saturation  = QTY stretch  / stretch capacity

Capacity is modelled per AC x supplier (one dedicated line/mould per AC and supplier).
"""

import numpy as np
import pandas as pd

from . import config as C
from .world import ac_demand, forecast_quarters

# Expected classification of each planted case, checked against the computed truth.
EXPECTED_SEVERITY = {
    "normal": "none",
    "both_saturated": "high",
    "baseline_only": "medium",
    "future_breach": "early_warning",
    "single_quarter_spike": "temporary_spike",
    "monthly_capacity_entry": "none",   # decoy: looks saturated in the raw buyer file only
    "cm_not_qualified": "high",         # trap: looks "medium" if the unqualified CM is counted
    # snapshot events (snapshots.py)
    "capacity_added": "none",
    "cm_qualified": "medium",
}

EXPECTED_ACTION = {
    "none": "no capacity action",
    "high": "RFQ for new capacity or investment (even all qualified CMs are not enough)",
    "medium": "activate CM short term, consider RFQ / investment to restore buffer",
    "early_warning": "plan RFQ / investment before the breach quarter",
    "temporary_spike": "no RFQ: manage the one-off peak with stock build or CM",
}


def classify(baseline_sat: np.ndarray, stretch_sat: np.ndarray) -> tuple[str, int | None]:
    """Severity and index of the first quarter where baseline saturation exceeds the warn threshold."""
    over_base = np.flatnonzero(baseline_sat > C.WARN_THRESHOLD)
    over_stretch = np.flatnonzero(stretch_sat > C.WARN_THRESHOLD)
    first = int(over_base[0]) if len(over_base) else None
    if len(over_base) == 0:
        return "none", None
    if len(over_base) == 1:
        return "temporary_spike", first
    if len(over_stretch) >= 2:
        return "high", first
    if first >= 4:
        return "early_warning", first
    return "medium", first


def _pick_spikes(rng, products, bom, components, n):
    """Pick non-viral hero PFs and one capacity AC of each that (ideally) only that PF uses."""
    cap_acs = set(components.loc[components.family.map(lambda f: C.FAMILIES[f]["capacity"])
                                 & ~components.is_new, "ac_code"])
    usage = bom.groupby("ac_code").pf_code.nunique()
    heroes = products[products.is_hero & ~products.is_viral].pf_code.tolist()
    rng.shuffle(heroes)
    picks = []
    for pf in heroes:
        acs = [a for a in bom.loc[bom.pf_code == pf, "ac_code"] if a in cap_acs]
        if not acs:
            continue
        ac = min(acs, key=lambda a: usage[a])
        if usage[ac] == 1:
            picks.append((pf, ac))
        if len(picks) == n:
            break
    return picks


def plant_capacity(rng: np.random.Generator, products: pd.DataFrame, components: pd.DataFrame,
                   bom: pd.DataFrame, forecast: pd.DataFrame, sourcing: pd.DataFrame, suppliers: pd.DataFrame):
    """Returns (forecast_with_spikes, capacity, cm_capacity, cases)."""
    forecast = forecast.copy()
    fc_q = forecast_quarters()
    cases: dict[str, str] = {}
    case_detail: dict[str, str] = {}
    excluded: set[str] = set()

    # 1. Spikes are applied to the forecast first, because they change demand.
    for pf, ac in _pick_spikes(rng, products, bom, components, C.PLANTED_CASES["single_quarter_spike"]):
        k = int(rng.integers(4, 8))
        mask = (forecast.pf_code == pf) & (forecast.quarter == fc_q[k])
        forecast.loc[mask, ["qty_baseline", "qty_stretch"]] = (
            forecast.loc[mask, ["qty_baseline", "qty_stretch"]] * 2.3).round()
        cases[ac] = "single_quarter_spike"
        case_detail[ac] = f"one-off peak on {pf} in {fc_q[k]}"
        excluded |= set(bom.loc[bom.pf_code == pf, "ac_code"])

    d_base = ac_demand(bom, forecast, "qty_baseline")[fc_q]
    d_str = ac_demand(bom, forecast, "qty_stretch")[fc_q]

    # 2. Pick the other planted cases among hero capacity components.
    hero_acs = set(bom.loc[bom.pf_code.isin(products.loc[products.is_hero, "pf_code"]), "ac_code"])
    sourced = set(sourcing.ac_code)
    cap_acs = [a for a in components.loc[components.family.map(lambda f: C.FAMILIES[f]["capacity"]), "ac_code"]
               if a in sourced]
    pool = [a for a in cap_acs if a in hero_acs and a not in excluded]
    growth = {a: d_base.loc[a].iloc[-1] / max(d_base.loc[a].iloc[0], 1) for a in pool}
    growing = sorted((a for a in pool if growth[a] >= 1.2), key=lambda a: -growth[a])
    for a in growing[: C.PLANTED_CASES["future_breach"]]:
        cases[a] = "future_breach"
    remaining = [a for a in pool if a not in cases]
    rng.shuffle(remaining)
    for case in ("both_saturated", "baseline_only", "monthly_capacity_entry", "cm_not_qualified"):
        for _ in range(C.PLANTED_CASES[case]):
            cases[remaining.pop()] = case

    # 3. Size capacities so that each AC behaves as its case says.
    cms = suppliers[suppliers.supplier_type == "contract_manufacturer"].supplier_id.tolist()
    cap_rows, cm_rows = [], []
    u = rng.uniform
    for a in cap_acs:
        db, ds = d_base.loc[a].to_numpy(float), d_str.loc[a].to_numpy(float)
        db_now, ds_now = db[:4].max(), ds[:4].max()
        case = cases.get(a, "normal")
        cm_cap, qualified = 0.0, True
        if case in ("normal", "monthly_capacity_entry"):
            total = max(db.max() / u(0.5, 0.75), ds.max() / u(0.6, 0.8), 1000)
            if rng.random() < 0.4:
                cm_cap, qualified = total * u(0.1, 0.3), rng.random() < 0.85
        elif case == "both_saturated":
            total = db_now / u(1.0, 1.15)
            cm_cap = max(ds_now / u(0.95, 1.1) - total, 0.05 * total)
        elif case == "baseline_only":
            total = db_now / u(0.9, 1.0)
            cm_cap = ds.max() / u(0.6, 0.75) - total
        elif case == "future_breach":
            total = db[8] / 0.9
            cm_cap = max(ds.max() / u(0.6, 0.75) - total, 0.0)
        elif case == "single_quarter_spike":
            k = int(np.argmax(db))
            total = db[k] / u(1.05, 1.2)
            cm_cap = 0.3 * total
        elif case == "cm_not_qualified":
            total = db_now / u(0.9, 1.0)
            cm_cap, qualified = ds.max() / u(0.6, 0.75) - total, False

        for s in sourcing[sourcing.ac_code == a].itertuples():
            cap_rows.append({"ac_code": a, "supplier_id": s.supplier_id,
                             "line_id": f"{s.supplier_id}-L{len(cap_rows) + 1:03d}",
                             "capacity_per_quarter": int(round(total * s.share, -2))})
        if cm_cap > 0:
            cm_rows.append({"ac_code": a, "cm_id": cms[rng.integers(len(cms))],
                            "available_capacity_per_quarter": int(round(cm_cap, -2)), "qualified": qualified})
        if case == "monthly_capacity_entry":
            case_detail[a] = "true capacity is quarterly; raw buyer file holds the monthly figure"
        elif case == "cm_not_qualified":
            case_detail[a] = "CM listed with capacity but not qualified for this AC"

    capacity, cm_capacity = pd.DataFrame(cap_rows), pd.DataFrame(cm_rows)
    case_df = pd.DataFrame([{"ac_code": a, "case": cases.get(a, "normal"), "detail": case_detail.get(a, "")}
                            for a in cap_acs])
    return forecast, capacity, cm_capacity, case_df


def compute_saturation(bom, forecast, capacity, cm_capacity, fc_q: list[str] | None = None) -> pd.DataFrame:
    """True saturation per AC x forecast quarter (qualified CMs only in stretch capacity)."""
    fc_q = fc_q or forecast_quarters()
    d_base = ac_demand(bom, forecast, "qty_baseline")[fc_q]
    d_str = ac_demand(bom, forecast, "qty_stretch")[fc_q]
    base_cap = capacity.groupby("ac_code").capacity_per_quarter.sum()
    cm_q = cm_capacity[cm_capacity.qualified].groupby("ac_code").available_capacity_per_quarter.sum()
    rows = []
    for a, bc in base_cap.items():
        sc = bc + cm_q.get(a, 0)
        for q in fc_q:
            b, s = d_base.loc[a, q], d_str.loc[a, q]
            rows.append({"ac_code": a, "quarter": q, "qty_baseline": int(b), "qty_stretch": int(s),
                         "baseline_capacity": int(bc), "stretch_capacity": int(sc),
                         "baseline_saturation": round(b / bc, 4), "stretch_saturation": round(s / sc, 4),
                         # cross cases for the full matrix in the business case
                         "baseline_qty_on_stretch_capacity": round(b / sc, 4),
                         "stretch_qty_on_baseline_capacity": round(s / bc, 4)})
    return pd.DataFrame(rows)


def label_cases(cases: pd.DataFrame, saturation: pd.DataFrame, fc_q: list[str] | None = None,
                expected: dict[str, str] | None = None) -> pd.DataFrame:
    """Adds the severity computed from the truth, the expected severity and the expected action.

    `expected` overrides the expected severity per AC (used for the snapshot events)."""
    fc_q = fc_q or forecast_quarters()
    expected = expected or {}
    out = []
    for r in cases.itertuples():
        sat = saturation[saturation.ac_code == r.ac_code].set_index("quarter").loc[fc_q]
        sev, first = classify(sat.baseline_saturation.to_numpy(), sat.stretch_saturation.to_numpy())
        exp = expected[r.ac_code] if r.ac_code in expected else EXPECTED_SEVERITY[r.case]
        out.append({"ac_code": r.ac_code, "case": r.case, "detail": r.detail,
                    "severity": sev, "expected_severity": exp,
                    "first_breach_quarter": fc_q[first] if first is not None else None,
                    "peak_baseline_saturation": round(float(sat.baseline_saturation.max()), 3),
                    "peak_stretch_saturation": round(float(sat.stretch_saturation.max()), 3),
                    "expected_action": EXPECTED_ACTION[exp]})
    return pd.DataFrame(out)
