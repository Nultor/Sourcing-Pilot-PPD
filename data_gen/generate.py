"""Generate the synthetic packaging-sourcing dataset: two quarterly snapshots.

    python -m data_gen.generate                 # default seed, writes data/synthetic/
    python -m data_gen.generate --seed 7 --out /tmp/synth

Output:
    <out>/2026Q3/raw/            messy source-system exports (what the pipeline ingests)
    <out>/2026Q3/ground_truth/   clean tables, planted cases and the issues manifest (for evals only)
    <out>/2026Q4/...             same, one quarter later
    <out>/changes_2026Q3_to_2026Q4.csv   everything that changed between the two snapshots
"""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .messy import Exporter
from .saturation import compute_saturation, label_cases, plant_capacity
from .snapshots import roll_forward
from .world import (ac_demand, build_components_and_bom, build_fx, build_price_breakdowns, build_products,
                    build_sourcing, build_std_prices, build_suppliers, forecast_quarters, history_quarters,
                    quarter_label)


def build_world(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    suppliers = build_suppliers()
    products, sales, forecast = build_products(rng)
    components, bom = build_components_and_bom(rng, products)
    demand = ac_demand(bom, forecast, "qty_baseline")[forecast_quarters()]
    sourcing = build_sourcing(rng, components, suppliers, demand)
    forecast, capacity, cm_capacity, cases = plant_capacity(rng, products, components, bom, forecast,
                                                            sourcing, suppliers)
    saturation = compute_saturation(bom, forecast, capacity, cm_capacity)
    fx_quarters = history_quarters() + [quarter_label(*C.NEXT_QUARTER)]
    return {
        "rng": rng, "quarter": quarter_label(*C.LAST_CLOSED_QUARTER), "snapshot_date": C.SNAPSHOT_DATE,
        "suppliers": suppliers, "products": products, "sales": sales, "forecast": forecast,
        "components": components, "bom": bom, "sourcing": sourcing,
        "std_prices": build_std_prices(rng, sourcing),
        "price_breakdowns": build_price_breakdowns(rng, sourcing, components),
        "fx": build_fx(rng, fx_quarters), "capacity": capacity, "cm_capacity": cm_capacity,
        "saturation": saturation, "planted_cases": label_cases(cases, saturation),
    }


def rfq_candidates(w: dict) -> pd.DataFrame:
    """Expected RFQ triggers: A capacity, B new components for launches, C 3-year review."""
    rows = []
    for r in w["planted_cases"].itertuples():
        if r.expected_severity not in ("none", "temporary_spike"):
            rows.append({"trigger": "A_capacity", "ac_code": r.ac_code, "supplier_id": None,
                         "reason": f"{r.expected_severity}: {r.case}", "due": r.first_breach_quarter})
    launch = w["products"].set_index("pf_code").launch_quarter
    new_acs = w["components"][w["components"].is_new].ac_code
    for b in w["bom"][w["bom"].ac_code.isin(new_acs)].itertuples():
        rows.append({"trigger": "B_new_product", "ac_code": b.ac_code, "supplier_id": None,
                     "reason": f"new component for launch {b.pf_code}", "due": launch[b.pf_code]})
    snap = date.fromisoformat(w["snapshot_date"])
    cutoff = date(snap.year - 3, snap.month, snap.day)
    for s in w["sourcing"][w["sourcing"].last_rfq_date <= cutoff].itertuples():
        rows.append({"trigger": "C_review", "ac_code": s.ac_code, "supplier_id": s.supplier_id,
                     "reason": f"last RFQ {s.last_rfq_date} (> 3 years)", "due": None})
    return pd.DataFrame(rows)


def write_snapshot(out: Path, w: dict) -> dict:
    ex = Exporter(w["rng"], w)
    raw, gt = out / "raw", out / "ground_truth"
    raw.mkdir(parents=True, exist_ok=True)
    gt.mkdir(parents=True, exist_ok=True)

    exports = {
        "finance_sales_history.csv": ex.finance_sales_history(),
        "finance_forecast.csv": ex.finance_forecast(),
        "finance_std_cost.csv": ex.finance_std_cost(),
        "finance_fx_rates.csv": w["fx"][w["fx"].quarter <= w["quarter"]],
        "site_bom_moq.csv": ex.site_bom_moq(),
        "site_production.csv": ex.site_production(),
        "erp_pir.csv": ex.erp_pir(),
        "sourcing_contracts.csv": ex.sourcing_contracts(),
        "price_breakdown.csv": ex.price_breakdown(),
        "component_master.csv": ex.component_master(),
    }
    for name, df in exports.items():
        df.to_csv(raw / name, index=False)
    capacity_file = ex.buyer_capacity_file(w["planted_cases"])
    with pd.ExcelWriter(raw / "buyer_capacity_file.xlsx") as xl:
        capacity_file.to_excel(xl, sheet_name="Capacity", index=False)
        pd.DataFrame({"Notes": [
            "Capacity per supplier line, updated by buyers.",
            "CM = contract manufacturer capacity available but not used today.",
            "Please update the 'Last update' column when you change a value.",
        ]}).to_excel(xl, sheet_name="Notes", index=False)

    products = w["products"].drop(columns=["base_qty", "growth", "stretch_factor", "launch_index"])
    truth = {
        "suppliers.csv": w["suppliers"], "products.csv": products,
        "components.csv": w["components"], "bom.csv": w["bom"], "sales_history.csv": w["sales"],
        "forecast.csv": w["forecast"], "sourcing.csv": w["sourcing"], "std_prices.csv": w["std_prices"],
        "price_breakdowns.csv": w["price_breakdowns"], "capacity.csv": w["capacity"],
        "cm_capacity.csv": w["cm_capacity"], "saturation.csv": w["saturation"],
        "planted_cases.csv": w["planted_cases"], "rfq_candidates.csv": rfq_candidates(w),
        "supplier_aliases.csv": pd.DataFrame(sorted(ex.aliases), columns=["alias", "supplier_id", "source"]),
    }
    for name, df in truth.items():
        df.to_csv(gt / name, index=False)
    (gt / "issues_manifest.json").write_text(json.dumps(ex.issues, indent=2, ensure_ascii=False))

    summary = {
        "quarter": w["quarter"], "snapshot_date": w["snapshot_date"], "products": len(products),
        "heroes": int(products.is_hero.sum()), "npd_products": int(products.is_npd.sum()),
        "components": len(w["components"]),
        "suppliers": int((w["suppliers"].supplier_type == "supplier").sum()),
        "contract_manufacturers": int((w["suppliers"].supplier_type != "supplier").sum()),
        "planted_cases": Counter(w["planted_cases"].case),
        "rfq_candidates": Counter(truth["rfq_candidates.csv"].trigger),
        "issues": Counter(i["issue"] for i in ex.issues),
        "case_mismatches": int((w["planted_cases"].severity != w["planted_cases"].expected_severity).sum()),
    }
    (gt / "summary.json").write_text(json.dumps(summary, indent=2, default=dict))
    return summary


def write(out: Path, seed: int) -> dict:
    w = build_world(seed)
    first = write_snapshot(out / w["quarter"], w)
    w_next, changes = roll_forward(np.random.default_rng(seed + 1), w, C.NEXT_QUARTER, C.NEXT_SNAPSHOT_DATE)
    second = write_snapshot(out / w_next["quarter"], w_next)
    changes.to_csv(out / f"changes_{w['quarter']}_to_{w_next['quarter']}.csv", index=False)
    return {w["quarter"]: first, w_next["quarter"]: second, "changes": Counter(changes.change)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=C.SEED)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()
    print(json.dumps(write(args.out, args.seed), indent=2, default=dict))


if __name__ == "__main__":
    main()
