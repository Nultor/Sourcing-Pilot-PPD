"""Roll the world forward by one quarter (Q -> Q+1).

What happens between two quarterly snapshots:
  - the quarter closes: actual sales are added, the oldest history quarter drops out
  - finance publishes a new forecast: every PF is revised, viral products upwards,
    and one more quarter is added at the end of the 3-year horizon
  - planted events change the sourcing / capacity situation (see EVENTS)
Every change is recorded, so the pipeline's "what changed" report can be evaluated.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .saturation import EXPECTED_ACTION, compute_saturation, label_cases
from .world import ac_demand, forecast_quarters, history_quarters, quarter_label

EVENTS = {
    "capacity_added": "supplier added a mould: a 'baseline_only' AC is no longer saturated",
    "capacity_reduced": "supplier reallocated a line: a healthy hero AC becomes saturated",
    "cm_qualified": "the CM was qualified: a 'cm_not_qualified' AC drops from high to medium",
    "buyer_fixed_entry": "buyer corrected one monthly capacity entry in the Excel file",
    "price_change": "new PIR prices (raw-material index) for ~10% of AC x supplier",
    "rfq_completed": "two 3-year reviews closed with a new contract and lower price",
}


def roll_forward(rng: np.random.Generator, w: dict, next_quarter: tuple[int, int], snapshot_date: str
                 ) -> tuple[dict, pd.DataFrame]:
    """Returns (world for the next snapshot, changes table)."""
    hist_q, fc_q = history_quarters(next_quarter), forecast_quarters(next_quarter)
    closed = quarter_label(*next_quarter)
    products = w["products"].set_index("pf_code")
    changes = []

    def log(change, ac=None, supplier=None, pf=None, before=None, after=None, note=""):
        changes.append({"change": change, "ac_code": ac, "supplier_id": supplier, "pf_code": pf,
                        "before": before, "after": after, "note": note})

    # 1. Close the quarter: actuals = previous forecast with noise (viral products overshoot).
    prev_fc = w["forecast"].set_index(["pf_code", "quarter"])
    new_sales = []
    for pf, p in products.iterrows():
        planned = prev_fc.loc[(pf, closed), "qty_baseline"]
        if planned <= 0:
            continue
        factor = rng.uniform(1.1, 1.2) if p.is_viral else rng.normal(1, 0.06)
        new_sales.append({"pf_code": pf, "quarter": closed, "qty_sold": int(round(planned * factor))})
    sales = pd.concat([w["sales"][w["sales"].quarter.isin(hist_q)], pd.DataFrame(new_sales)], ignore_index=True)

    # 2. New forecast version: revise every PF, add one quarter at the end of the horizon.
    fc = w["forecast"][w["forecast"].quarter.isin(fc_q)].copy()
    revision = {pf: (rng.uniform(1.1, 1.2) if p.is_viral else rng.uniform(0.96, 1.04))
                for pf, p in products.iterrows()}
    for pf, r in revision.items():
        if products.loc[pf, "is_viral"]:
            log("forecast_revised", pf=pf, before=1.0, after=round(r, 3), note="viral product revised upwards")
    fc[["qty_baseline", "qty_stretch"]] = (fc[["qty_baseline", "qty_stretch"]]
                                           .mul(fc.pf_code.map(revision), axis=0).round().astype(int))
    last_old, new_q = fc_q[-2], fc_q[-1]
    tail = fc[fc.quarter == last_old].copy()
    g = tail.pf_code.map(products["growth"])
    season = 1.1 if new_q.endswith("Q4") else (1 / 1.1 if last_old.endswith("Q4") else 1.0)
    tail["qty_baseline"] = (tail.qty_baseline * (1 + g) * season).round().astype(int)
    tail["qty_stretch"] = (tail.qty_baseline * tail.pf_code.map(products["stretch_factor"])).round().astype(int)
    tail["quarter"] = new_q
    forecast = pd.concat([fc, tail], ignore_index=True).sort_values(["pf_code", "quarter"], ignore_index=True)

    # 3. Planted events.
    capacity, cm = w["capacity"].copy(), w["cm_capacity"].copy()
    sourcing = w["sourcing"].copy()
    cases = w["planted_cases"][["ac_code", "case", "detail"]].copy()
    d_base = ac_demand(w["bom"], forecast, "qty_baseline")[fc_q]
    by_case = lambda c: cases[cases.case == c].ac_code.tolist()
    expected = {}

    ac = by_case("baseline_only")[0]
    before = int(capacity[capacity.ac_code == ac].capacity_per_quarter.sum())
    capacity.loc[capacity.ac_code == ac, "capacity_per_quarter"] = (
        capacity.loc[capacity.ac_code == ac, "capacity_per_quarter"] * d_base.loc[ac].max() / 0.7 / before
    ).round(-2).astype(int)
    after = int(capacity[capacity.ac_code == ac].capacity_per_quarter.sum())
    log("capacity_added", ac=ac, before=before, after=after, note=EVENTS["capacity_added"])
    cases.loc[cases.ac_code == ac, ["case", "detail"]] = ["capacity_added", EVENTS["capacity_added"]]

    sat_prev = w["saturation"].groupby("ac_code").baseline_saturation.max()
    hero_acs = set(w["bom"][w["bom"].pf_code.isin(products.index[products.is_hero])].ac_code)
    healthy = [a for a in by_case("normal") if a in hero_acs and a in sat_prev.index]
    ac = max(healthy, key=lambda a: sat_prev[a])
    rows = capacity.ac_code == ac
    before = int(capacity[rows].capacity_per_quarter.sum())
    target = d_base.loc[ac].iloc[:4].min() / rng.uniform(0.9, 1.0)  # every quarter above the warn level
    capacity.loc[rows, "capacity_per_quarter"] = (
        capacity.loc[rows, "capacity_per_quarter"] * target / before).round(-2).astype(int)
    log("capacity_reduced", ac=ac, before=before, after=int(capacity[rows].capacity_per_quarter.sum()),
        note=EVENTS["capacity_reduced"])
    cases.loc[cases.ac_code == ac, ["case", "detail"]] = ["capacity_reduced", EVENTS["capacity_reduced"]]
    expected[ac] = "medium"  # placeholder: medium or high depending on its CM, set from the truth below

    ac = by_case("cm_not_qualified")[0]
    cm.loc[cm.ac_code == ac, "qualified"] = True
    log("cm_qualified", ac=ac, supplier=cm[cm.ac_code == ac].cm_id.iloc[0], before=False, after=True,
        note=EVENTS["cm_qualified"])
    cases.loc[cases.ac_code == ac, ["case", "detail"]] = ["cm_qualified", EVENTS["cm_qualified"]]

    ac = by_case("monthly_capacity_entry")[0]
    cases.loc[cases.ac_code == ac, ["case", "detail"]] = ["normal", "buyer corrected the monthly figure"]
    log("buyer_fixed_entry", ac=ac, note=EVENTS["buyer_fixed_entry"])

    snap = date.fromisoformat(snapshot_date)
    price_date = snap - timedelta(days=60)
    for i in sourcing.sample(frac=0.1, random_state=int(rng.integers(1 << 31))).index:
        old = sourcing.at[i, "unit_price_eur"]
        sourcing.at[i, "unit_price_eur"] = round(old * rng.uniform(1.02, 1.08), 4)
        sourcing.at[i, "price_valid_from"] = price_date
        log("price_change", ac=sourcing.at[i, "ac_code"], supplier=sourcing.at[i, "supplier_id"],
            before=old, after=sourcing.at[i, "unit_price_eur"], note="raw-material index increase")

    cutoff = date(snap.year - 3, snap.month, snap.day)
    capacity_cases = set(cases[cases.case != "normal"].ac_code)
    single = sourcing.groupby("ac_code").supplier_id.transform("count") == 1
    due = sourcing[(sourcing.last_rfq_date <= cutoff) & single & ~sourcing.ac_code.isin(capacity_cases)]
    for i in due.sample(n=2, random_state=int(rng.integers(1 << 31))).index:
        old = sourcing.at[i, "unit_price_eur"]
        start = snap - timedelta(days=30)
        sourcing.loc[i, ["last_rfq_date", "contract_start", "price_valid_from", "contract_end"]] = [
            snap - timedelta(days=75), start, start, start + timedelta(days=3 * 365)]
        sourcing.at[i, "unit_price_eur"] = round(old * rng.uniform(0.9, 0.96), 4)
        log("rfq_completed", ac=sourcing.at[i, "ac_code"], supplier=sourcing.at[i, "supplier_id"],
            before=old, after=sourcing.at[i, "unit_price_eur"], note="new 3-year contract after RFQ")

    # 4. New truth.
    saturation = compute_saturation(w["bom"], forecast, capacity, cm, fc_q)
    planted = label_cases(cases, saturation, fc_q, expected)
    capacity_reduced = planted.case == "capacity_reduced"
    planted.loc[capacity_reduced, "expected_severity"] = planted.loc[capacity_reduced, "severity"]
    planted.loc[capacity_reduced, "expected_action"] = planted.loc[capacity_reduced, "severity"].map(EXPECTED_ACTION)
    prev = w["planted_cases"].set_index("ac_code").severity
    for r in planted.itertuples():
        if prev.get(r.ac_code) != r.severity:
            log("severity_changed", ac=r.ac_code, before=prev.get(r.ac_code), after=r.severity,
                note=r.case if r.case != "normal" else "forecast revision / new actuals")

    w2 = {**w, "quarter": closed, "snapshot_date": snapshot_date, "sales": sales, "forecast": forecast,
          "sourcing": sourcing, "capacity": capacity, "cm_capacity": cm, "saturation": saturation,
          "planted_cases": planted, "rng": rng}
    return w2, pd.DataFrame(changes)

