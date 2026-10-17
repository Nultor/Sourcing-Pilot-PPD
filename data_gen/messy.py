"""Messy source-system exports derived from the clean world.

Each source system has its own naming conventions (supplier names, component
descriptions, units, code formats) and some random human errors. Every injected
error is logged in the issues manifest with its true value and how to fix it, so
the data-quality step of the pipeline can be evaluated.
"""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C

_LEGAL_SUFFIX = re.compile(r"\s+(SAS|S\.L\.|GmbH|S\.p\.A\.|Inc|Ltd|SARL|SA|S\.A\.|Lda)$")
OPEN_END = "9999-12-31"


def supplier_name_styles(name: str, short: str) -> dict[str, str]:
    """The naming styles used by the different source systems for one supplier."""
    stripped = _LEGAL_SUFFIX.sub("", name)
    return {
        "legal": name,                       # ERP / PIR
        "legal_no_punct": name.replace(".", ""),
        "stripped": stripped,                # contracts, price breakdowns
        "stripped_upper": stripped.upper(),
        "short": short,                      # production site
        "short_upper": short.upper(),
    }


def _typo(rng, s: str) -> str:
    i = int(rng.integers(1, len(s) - 1))
    return s[:i] + s[i + 1:]


def _format_str(rng, ml: int) -> str:
    if ml >= 500 and rng.random() < 0.6:
        litres = f"{ml / 1000:g}"
        return [f"{litres} L", f"{litres}L", f"{litres.replace('.', ',')} L"][rng.integers(3)]
    return [f"{ml} ml", f"{ml}ML", f"{ml}ml"][rng.integers(3)]


class Exporter:
    def __init__(self, rng: np.random.Generator, world: dict):
        self.rng = rng
        self.w = world
        self.issues: list[dict] = []
        self.aliases: set[tuple[str, str, str]] = set()  # (alias, supplier_id, source)
        sup = world["suppliers"].set_index("supplier_id")
        self.styles = {sid: supplier_name_styles(r.supplier_name, r.short_name) for sid, r in sup.iterrows()}
        self.comp = world["components"].set_index("ac_code")
        self.prod = world["products"].set_index("pf_code")
        main = world["sourcing"].sort_values("share", ascending=False).drop_duplicates("ac_code")
        self.main_supplier = main.set_index("ac_code")["supplier_id"]
        self.snapshot = date.fromisoformat(world["snapshot_date"])
        self.quarter = world["quarter"]
        fx = world["fx"]
        self.fx_now = fx[fx.quarter == self.quarter].set_index("currency")["rate_to_eur"]

    # ------------------------------------------------------------------ helpers
    def log(self, issue, table, key, column, raw, true, fix):
        self.issues.append({"id": len(self.issues) + 1, "issue": issue, "table": table, "key": key,
                            "column": column, "raw_value": None if raw is None else str(raw),
                            "true_value": None if true is None else str(true), "how_to_fix": fix})

    def sup_name(self, sid, style, source):
        name = self.styles[sid][style]
        self.aliases.add((name, sid, source))
        return name

    def _desc(self, ac, style_idx):
        c = self.comp.loc[ac]
        fam = C.FAMILY_NAMES[c.family][style_idx]
        if C.FAMILIES[c.family]["brand_specific"]:
            pf_fmt = f" {int(c.size_ml)}ml" if not pd.isna(c.size_ml) else ""
            return f"{fam} {c.brand}{pf_fmt}"
        if not pd.isna(c.size_ml):
            return f"{fam} {c.material} {int(c.size_ml)}ml"
        return f"{fam} {c.material} {c.neck}"

    def chance(self, p):
        return self.rng.random() < p

    # ------------------------------------------------------------------ finance
    def finance_sales_history(self) -> pd.DataFrame:
        t = "finance_sales_history.csv"
        fmt = {pf: _format_str(self.rng, int(r.format_ml)) for pf, r in self.prod.iterrows()}
        price = {b: self.rng.uniform(8, 40) for b in C.BRANDS}
        rows = []
        for s in self.w["sales"].itertuples():
            p = self.prod.loc[s.pf_code]
            code = s.pf_code
            if self.chance(0.02):
                code = [code.lower(), code + " ", " " + code][self.rng.integers(3)]
                self.log("code_format", t, {"pf_code": s.pf_code, "quarter": s.quarter}, "PF Code",
                         code, s.pf_code, "strip spaces and upper-case the PF code")
            rows.append({"PF Code": code, "PF Description": p.pf_description.upper(), "Brand": p.brand,
                         "Format": fmt[s.pf_code], "Business Driver": "Y" if p.is_hero else "N",
                         "Quarter": s.quarter, "Qty Sold": s.qty_sold,
                         "Net Sales EUR": round(s.qty_sold * price[p.brand], 2)})
        df = pd.DataFrame(rows)
        dup_idx = df.sample(frac=0.01, random_state=int(self.rng.integers(1 << 31))).index
        for i in dup_idx:
            self.log("duplicate_row", t, {"pf_code": df.at[i, "PF Code"].strip().upper(),
                                          "quarter": df.at[i, "Quarter"]},
                     None, None, None, "drop exact duplicate rows before aggregating")
        df = pd.concat([df, df.loc[dup_idx]]).sort_values(["Quarter", "PF Code"]).reset_index(drop=True)
        self.log("unit_mix", t, {"rows": "all"}, "Format", "ml and L mixed (e.g. '0,5 L', '500ML')",
                 "format in ml", "parse number (comma or dot decimal) and unit, convert L to ml")
        return df

    def finance_forecast(self) -> pd.DataFrame:
        t = "finance_forecast.csv"
        rows = []
        for f in self.w["forecast"].itertuples():
            stretch = f.qty_stretch
            if self.chance(0.02) and f.qty_baseline > 0:
                self.log("missing_unrecoverable", t, {"pf_code": f.pf_code, "quarter": f.quarter},
                         "QTY Stretch", None, f.qty_stretch,
                         "no other source: flag it, use an explicit assumption (e.g. PF stretch ratio "
                         "from the other quarters) and record it in the assumptions log")
                stretch = None
            rows.append({"PF": f.pf_code, "Quarter": f.quarter, "QTY Baseline": f.qty_baseline,
                         "QTY Stretch": stretch, "Forecast Version": f"FC_{self.quarter}"})
        return pd.DataFrame(rows).astype({"QTY Stretch": "Int64"})

    def finance_std_cost(self) -> pd.DataFrame:
        t = "finance_std_cost.csv"
        rows = []
        for s in self.w["std_prices"].itertuples():
            value = s.std_price_eur_per_1000
            if s.fiscal_year == 2026 and self.chance(0.03):
                self.log("missing_value", t, {"ac_code": s.ac_code, "fiscal_year": 2026}, "STD Price (EUR/1000)",
                         None, value, "not recoverable exactly; FY2025 STD or current PIR price can be used "
                                      "as a documented assumption")
                value = None
            rows.append({"AC Code": f"{s.ac_code}.0", "AC Description": self._desc(s.ac_code, 1).upper(),
                         "Fiscal Year": s.fiscal_year, "STD Price (EUR/1000)": value})
        self.log("code_format", t, {"rows": "all"}, "AC Code", "361234567.0", "361234567",
                 "codes exported as floats: drop the trailing '.0'")
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ production site
    def site_bom_moq(self) -> pd.DataFrame:
        t = "site_bom_moq.csv"
        src = self.w["sourcing"].set_index(["ac_code", "supplier_id"])
        rows = []
        existing = set(self.prod.index[~self.prod.is_npd])
        for b in self.w["bom"].itertuples():
            if b.pf_code not in existing:
                continue
            c = self.comp.loc[b.ac_code]
            sid = self.main_supplier[b.ac_code]
            supplier = self.sup_name(sid, "short_upper" if self.chance(0.1) else "short", "site")
            if self.chance(0.05):
                self.log("missing_recoverable", t, {"pf_code": b.pf_code, "ac_code": b.ac_code}, "Supplier",
                         None, self.styles[sid]["legal"],
                         "look up the AC in erp_pir.csv (plant P100, valid today, not deleted)")
                supplier = None
            material = c.material
            if self.chance(0.06):
                self.log("missing_recoverable", t, {"pf_code": b.pf_code, "ac_code": b.ac_code}, "Material",
                         None, c.material, "take the material from component_master.csv via the AC code")
                material = None
            code = b.ac_code
            if self.chance(0.03):
                code = f" {code} " if self.chance(0.5) else f"{code} "
                self.log("code_format", t, {"pf_code": b.pf_code, "ac_code": b.ac_code}, "AC Code",
                         code, b.ac_code, "strip spaces")
            rows.append({"Plant": "P100", "PF Code": b.pf_code, "AC Code": code,
                         "AC Description": self._desc(b.ac_code, 2), "Qty per PF": b.qty_per_pf,
                         "Material": material, "Supplier": supplier,
                         "MOQ (pcs)": int(src.loc[(b.ac_code, sid), "moq_pcs"])})
        return pd.DataFrame(rows)

    def site_production(self) -> pd.DataFrame:
        t = "site_production.csv"
        rows = []
        for s in self.w["sales"].itertuples():
            if self.chance(0.015):
                self.log("missing_row", t, {"pf_code": s.pf_code, "quarter": s.quarter}, "Qty Produced",
                         None, None, "quarter missing for this PF; use finance sales as proxy and log it")
                continue
            rows.append({"Plant": "P100", "PF Code": s.pf_code, "Quarter": s.quarter,
                         "Qty Produced": int(round(s.qty_sold * self.rng.uniform(0.95, 1.08)))})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ purchasing (ERP)
    def erp_pir(self) -> pd.DataFrame:
        t = "erp_pir.csv"
        rows = []
        snapshot = self.snapshot
        single = self.w["sourcing"].groupby("ac_code").supplier_id.transform("count") == 1
        expired_acs = set(self.w["sourcing"][single].ac_code.sample(
            n=2, random_state=int(self.rng.integers(1 << 31))))

        def add(s, plant, price_eur, valid_from, valid_to, moq, deleted=""):
            cur_price = price_eur / self.fx_now[s.currency] * s.price_unit
            style = "legal_no_punct" if self.chance(0.05) else "legal"
            rows.append({"PIR No": f"53{len(rows) + 10_000_000:08d}", "AC Code": s.ac_code,
                         "Supplier": self.sup_name(s.supplier_id, style, "erp"), "Plant": plant,
                         "Net Price": round(cur_price, 4 if s.price_unit == 1 else 2), "Currency": s.currency,
                         "Price Unit": s.price_unit, "Valid From": str(valid_from), "Valid To": str(valid_to),
                         "Lead Time (days)": s.lead_time_days, "Min Order Qty": moq, "Deletion Flag": deleted})
            return len(rows) - 1

        for s in self.w["sourcing"].itertuples():
            key = {"ac_code": s.ac_code, "supplier": self.styles[s.supplier_id]["legal"]}
            # history
            start = s.price_valid_from
            for _ in range(int(self.rng.integers(1, 3))):
                prev_start = start - timedelta(days=int(self.rng.integers(365, 730)))
                add(s, "P100", s.unit_price_eur * self.rng.uniform(0.9, 1.02), prev_start,
                    start - timedelta(days=1), s.moq_pcs)
                start = prev_start
            # current record
            valid_to = OPEN_END
            if s.ac_code in expired_acs:
                valid_to = "2025-12-31"
                self.log("expired_pir_still_used", t, key, "Valid To", valid_to, OPEN_END,
                         "only an expired PIR exists while the AC is still produced: flag for the buyer")
            price = s.unit_price_eur
            moq = s.moq_pcs
            if self.chance(0.08):
                moq = int(moq * [0.5, 2][self.rng.integers(2)])
                self.log("moq_conflict", t, key, "Min Order Qty", moq, s.moq_pcs,
                         "PIR and site MOQ differ: site MOQ is the reference, confirm with the supplier")
            idx = add(s, "P100", price, s.price_valid_from, valid_to, moq)
            if self.chance(0.02):
                rows[idx]["Net Price"] = round(rows[idx]["Net Price"] * 10, 4)
                self.log("price_outlier", t, {**key, "pir_no": rows[idx]["PIR No"]}, "Net Price",
                         rows[idx]["Net Price"], round(rows[idx]["Net Price"] / 10, 4),
                         "x10 typo: inconsistent with price history, STD price and price breakdown")
            # traps for naive filtering
            if self.chance(0.3):
                add(s, "P200", price * self.rng.uniform(1.0, 1.08), s.price_valid_from, OPEN_END, moq)
            if self.chance(0.04):
                i = add(s, "P100", price * self.rng.uniform(0.8, 0.95), snapshot - timedelta(days=60),
                        OPEN_END, moq, deleted="X")
                self.log("double_filter_trap", t, {**key, "pir_no": rows[i]["PIR No"]}, "Deletion Flag", "X", "X",
                         "filter plant = P100 AND valid today AND deletion flag empty")
        return pd.DataFrame(rows)

    def sourcing_contracts(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "AC Code": s.ac_code, "Supplier": self.sup_name(s.supplier_id, "stripped", "contracts"),
            "Contract Start": str(s.contract_start), "Contract End": str(s.contract_end),
            "Last RFQ Date": str(s.last_rfq_date)} for s in self.w["sourcing"].itertuples()])

    def price_breakdown(self) -> pd.DataFrame:
        t = "price_breakdown.csv"
        rows = []
        for b in self.w["price_breakdowns"].itertuples():
            if not self.chance(0.75):
                continue
            total = b.total_eur_per_1000
            if self.chance(0.03):
                total = round(total * self.rng.uniform(1.05, 1.2), 2)
                self.log("inconsistent_total", t, {"ac_code": b.ac_code, "supplier_id": b.supplier_id},
                         "Total", total, b.total_eur_per_1000, "total must equal the sum of cost lines")
            style = "stripped_upper" if self.chance(0.3) else "stripped"
            rows.append({"AC": b.ac_code, "Supplier": self.sup_name(b.supplier_id, style, "price_breakdown"),
                         "Currency": "EUR", "Unit": "per 1000 pcs", "Raw material": b.raw_material,
                         "Conversion": b.conversion, "Decoration": b.decoration, "Packaging": b.packaging,
                         "Transport": b.transport, "Overhead & margin": b.overhead_margin, "Total": total})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ R&D packaging / specs
    def component_master(self) -> pd.DataFrame:
        t = "component_master.csv"
        rows = []
        for ac, c in self.comp.iterrows():
            spec = C.FAMILIES[c.family]
            material, size, brand = c.material, c.size_ml, c.brand
            if self.chance(0.05):
                self.log("missing_recoverable", t, {"ac_code": ac}, "Material", None, material,
                         "take the material from site_bom_moq.csv via the AC code")
                material = None
            if spec["sized"] and self.chance(0.08):
                self.log("missing_recoverable", t, {"ac_code": ac}, "Size (ml)", None, int(size),
                         "AC -> PF via site_bom_moq.csv, then PF format from finance_sales_history.csv")
                size = None
            if spec["brand_specific"] and self.chance(0.15):
                self.log("missing_recoverable", t, {"ac_code": ac}, "Brand", None, brand,
                         "AC -> PF via site_bom_moq.csv, then brand from finance_sales_history.csv")
                brand = None
            rows.append({"AC Code": ac, "Description": c.description, "Family": C.FAMILY_NAMES[c.family][0],
                         "Material": material, "Size (ml)": None if pd.isna(size) else int(size),
                         "Neck": c.neck, "Colour": c.colour, "Weight (g)": c.weight_g,
                         "Technology": c.technology, "Brand": brand,
                         "Status": "in development" if c.is_new else "active"})
        return pd.DataFrame(rows).astype({"Size (ml)": "Int64"})

    # ------------------------------------------------------------------ buyer-maintained Excel
    def buyer_capacity_file(self, cases: pd.DataFrame) -> pd.DataFrame:
        t = "buyer_capacity_file.xlsx"
        case = cases.set_index("ac_code")["case"]
        cm = self.w["cm_capacity"].set_index("ac_code")
        comments = ["", "", "", "confirmed by supplier", "to be checked", "shared line", "new mould planned 2027"]
        rows = []
        seen = set()
        for r in self.w["capacity"].itertuples():
            c = self.comp.loc[r.ac_code]
            if self.chance(0.08):
                supplier = _typo(self.rng, self.styles[r.supplier_id]["short"])
                self.aliases.add((supplier, r.supplier_id, "buyer_file"))
                self.log("supplier_typo", t, {"ac_code": r.ac_code}, "Supplier", supplier,
                         self.styles[r.supplier_id]["legal"], "fuzzy-match against the supplier list")
            else:
                supplier = self.sup_name(r.supplier_id, ["short", "short_upper", "stripped"][self.rng.integers(3)],
                                         "buyer_file")
            value, unit = float(r.capacity_per_quarter), "pcs"
            if case.get(r.ac_code) == "monthly_capacity_entry":
                value = round(value / 3, -2)
                self.log("monthly_capacity_entry", t, {"ac_code": r.ac_code, "supplier_id": r.supplier_id},
                         "Capacity / quarter", value, r.capacity_per_quarter,
                         "value is monthly: historical production per quarter exceeds it; x3")
            if self.chance(0.15):
                value, unit = round(value / 1000, 1), "kpcs"
            desc = C.FAMILY_NAMES[c.family][3] if self.chance(0.3) else self._desc(r.ac_code, 3)
            row = {"AC": int(r.ac_code), "Description": desc, "Supplier": supplier, "Technology": c.technology,
                   "Line": r.line_id, "Capacity / quarter": value, "Unit": unit,
                   "CM": None, "CM available capacity / quarter": None, "CM qualified": None,
                   "Last update": str(self.snapshot - timedelta(days=int(self.rng.integers(1, 270)))),
                   "Comment": comments[self.rng.integers(len(comments))]}
            if r.ac_code in cm.index and r.ac_code not in seen:
                m = cm.loc[r.ac_code]
                row["CM"] = self.sup_name(m.cm_id, "short", "buyer_file")
                row["CM available capacity / quarter"] = m.available_capacity_per_quarter
                row["CM qualified"] = (["Y", "yes"] if m.qualified else ["N", "no"])[self.rng.integers(2)]
            if self.chance(0.05):
                stale = str(self.snapshot - timedelta(days=int(self.rng.integers(640, 940))))
                row["Last update"] = stale
                self.log("stale_value", t, {"ac_code": r.ac_code, "supplier_id": r.supplier_id}, "Last update",
                         stale, None, "capacity not updated for > 18 months: ask the supplier to confirm")
            seen.add(r.ac_code)
            rows.append(row)
        self.log("unit_mix", t, {"rows": "all"}, "Capacity / quarter", "pcs and kpcs mixed", "pcs",
                 "multiply kpcs rows by 1000")
        self.log("value_format", t, {"rows": "all"}, "CM qualified", "Y / yes / N / no", "boolean",
                 "normalise yes/no variants")
        return pd.DataFrame(rows).astype({"CM available capacity / quarter": "Int64"})
