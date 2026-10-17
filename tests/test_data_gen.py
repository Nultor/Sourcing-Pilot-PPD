import hashlib
import json

import pandas as pd
import pytest

from data_gen import config as C
from data_gen.generate import write

PF_RE, AC_RE = r"^E\d{5}$", r"^36\d{7}$"
Q3, Q4 = "2026Q3", "2026Q4"
SNAPSHOT_DATE = {Q3: C.SNAPSHOT_DATE, Q4: C.NEXT_SNAPSHOT_DATE}
both_quarters = pytest.mark.parametrize("q", [Q3, Q4])


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    path = tmp_path_factory.mktemp("synth")
    write(path, C.SEED)
    return path


def gt(out, q, name, **kw):
    return pd.read_csv(out / q / "ground_truth" / name, dtype={"ac_code": str, "pf_code": str}, **kw)


def raw(out, q, name, **kw):
    return pd.read_csv(out / q / "raw" / name, dtype=str, **kw)


def manifest(out, q):
    return json.loads((out / q / "ground_truth" / "issues_manifest.json").read_text())


def changes(out):
    return pd.read_csv(out / f"changes_{Q3}_to_{Q4}.csv", dtype={"ac_code": str})


@both_quarters
def test_codes_follow_the_division_format(out, q):
    assert gt(out, q, "products.csv").pf_code.str.match(PF_RE).all()
    assert gt(out, q, "components.csv").ac_code.str.match(AC_RE).all()
    assert raw(out, q, "site_bom_moq.csv")["AC Code"].str.strip().str.match(AC_RE).all()
    assert raw(out, q, "finance_sales_history.csv")["PF Code"].str.strip().str.upper().str.match(PF_RE).all()


@both_quarters
def test_truth_tables_are_consistent(out, q):
    products, components, bom = gt(out, q, "products.csv"), gt(out, q, "components.csv"), gt(out, q, "bom.csv")
    assert products.pf_code.is_unique and components.ac_code.is_unique
    assert set(bom.pf_code) <= set(products.pf_code)
    assert set(bom.ac_code) == set(components.ac_code)
    sourcing = gt(out, q, "sourcing.csv")
    assert (sourcing.groupby("ac_code").share.sum().round(2) == 1).all()
    # every existing component has a supplier, new NPD components do not
    new = set(components[components.is_new].ac_code)
    assert set(sourcing.ac_code) == set(components.ac_code) - new


@both_quarters
def test_planted_cases_match_their_expected_severity(out, q):
    cases = gt(out, q, "planted_cases.csv")
    assert (cases.severity == cases.expected_severity).all()


def test_first_snapshot_has_all_planted_cases(out):
    counts = gt(out, Q3, "planted_cases.csv").case.value_counts()
    for case, n in C.PLANTED_CASES.items():
        assert counts.get(case, 0) == n, case


@both_quarters
def test_every_issue_type_is_injected(out, q):
    found = {i["issue"] for i in manifest(out, q)}
    assert {"code_format", "duplicate_row", "unit_mix", "missing_recoverable", "missing_unrecoverable",
            "moq_conflict", "price_outlier", "expired_pir_still_used", "double_filter_trap",
            "inconsistent_total", "monthly_capacity_entry", "supplier_typo"} <= found


@both_quarters
def test_missing_suppliers_are_recoverable_from_pir(out, q):
    pir = raw(out, q, "erp_pir.csv")
    valid = pir[(pir.Plant == "P100") & (pir["Deletion Flag"].isna()) & (pir["Valid From"] <= SNAPSHOT_DATE[q])]
    for i in manifest(out, q):
        if i["issue"] == "missing_recoverable" and i["column"] == "Supplier":
            rows = valid[valid["AC Code"] == i["key"]["ac_code"]]
            assert i["true_value"] in set(rows.Supplier.str.replace(".", "")) | set(rows.Supplier)


@both_quarters
def test_missing_sizes_are_recoverable_via_pf(out, q):
    bom, products = gt(out, q, "bom.csv"), gt(out, q, "products.csv").set_index("pf_code")
    for i in manifest(out, q):
        if i["issue"] == "missing_recoverable" and i["column"] == "Size (ml)":
            pfs = bom[bom.ac_code == i["key"]["ac_code"]].pf_code
            assert {int(products.loc[p, "format_ml"]) for p in pfs} == {int(i["true_value"])}


@both_quarters
def test_monthly_capacity_decoy_is_a_third_of_the_truth(out, q):
    xl = pd.read_excel(out / q / "raw" / "buyer_capacity_file.xlsx", sheet_name="Capacity")
    xl["value_pcs"] = xl["Capacity / quarter"] * xl.Unit.map({"pcs": 1, "kpcs": 1000})
    truth = gt(out, q, "capacity.csv")
    decoys = [i for i in manifest(out, q) if i["issue"] == "monthly_capacity_entry"]
    assert decoys
    for i in decoys:
        k = i["key"]
        raw_v = xl[(xl.AC.astype(str) == k["ac_code"]) & (xl.Line.str.startswith(k["supplier_id"]))].value_pcs
        true_v = truth[(truth.ac_code == k["ac_code"]) & (truth.supplier_id == k["supplier_id"])]
        assert raw_v.iloc[0] * 3 == pytest.approx(true_v.capacity_per_quarter.iloc[0], rel=0.02)


# ---------------------------------------------------------------- second snapshot

def test_quarter_rolls_forward(out):
    q3, q4 = gt(out, Q3, "sales_history.csv"), gt(out, Q4, "sales_history.csv")
    assert q4.quarter.max() == Q4 and q4.quarter.min() > q3.quarter.min()
    assert q4.quarter.nunique() == q3.quarter.nunique() == C.HISTORY_QUARTERS
    fc = raw(out, Q4, "finance_forecast.csv")
    assert set(fc["Forecast Version"]) == {f"FC_{Q4}"}
    assert fc.Quarter.min() == "2027Q1" and fc.Quarter.nunique() == C.FORECAST_QUARTERS


def test_events_change_severity_as_intended(out):
    q4 = gt(out, Q4, "planted_cases.csv").set_index("ac_code")
    ch = changes(out)
    event_ac = lambda e: ch[ch.change == e].ac_code.iloc[0]
    assert q4.loc[event_ac("capacity_added"), "severity"] == "none"
    assert q4.loc[event_ac("cm_qualified"), "severity"] == "medium"
    assert q4.loc[event_ac("capacity_reduced"), "severity"] in ("medium", "high")
    assert gt(out, Q3, "planted_cases.csv").set_index("ac_code").loc[event_ac("capacity_reduced"), "severity"] == "none"
    fixed = event_ac("buyer_fixed_entry")
    assert fixed not in {i["key"]["ac_code"] for i in manifest(out, Q4) if i["issue"] == "monthly_capacity_entry"}


def test_completed_rfqs_leave_the_review_list(out):
    done = set(changes(out).query("change == 'rfq_completed'").ac_code)
    assert done and done <= set(gt(out, Q3, "rfq_candidates.csv").query("trigger == 'C_review'").ac_code)
    assert not done & set(gt(out, Q4, "rfq_candidates.csv").query("trigger == 'C_review'").ac_code)


def test_price_changes_appear_as_new_pir_records(out):
    pir = raw(out, Q4, "erp_pir.csv")
    for c in changes(out).query("change == 'price_change'").itertuples():
        recs = pir[(pir["AC Code"] == c.ac_code) & (pir.Plant == "P100") & pir["Deletion Flag"].isna()]
        assert (recs["Valid From"] > C.SNAPSHOT_DATE).any(), c.ac_code


def test_generation_is_deterministic(out, tmp_path):
    write(tmp_path, C.SEED)
    for f in [f"{Q3}/raw/erp_pir.csv", f"{Q4}/ground_truth/saturation.csv", f"changes_{Q3}_to_{Q4}.csv"]:
        assert hashlib.md5((out / f).read_bytes()).digest() == hashlib.md5((tmp_path / f).read_bytes()).digest()
