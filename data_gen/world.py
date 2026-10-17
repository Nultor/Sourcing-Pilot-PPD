"""Builds the clean ("ground truth") world: suppliers, products, components, BOM,
sales, forecasts and sourcing. Messy source-system exports are derived from it
in messy.py; the pipeline is later evaluated against these clean tables.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C


# --------------------------------------------------------------------------- quarters

def _shift_quarter(year: int, q: int, n: int) -> tuple[int, int]:
    idx = year * 4 + (q - 1) + n
    return idx // 4, idx % 4 + 1


def quarter_label(year: int, q: int) -> str:
    return f"{year}Q{q}"


def history_quarters(last: tuple[int, int] | None = None) -> list[str]:
    y, q = last or C.LAST_CLOSED_QUARTER
    return [quarter_label(*_shift_quarter(y, q, -i)) for i in range(C.HISTORY_QUARTERS - 1, -1, -1)]


def forecast_quarters(last: tuple[int, int] | None = None) -> list[str]:
    y, q = last or C.LAST_CLOSED_QUARTER
    return [quarter_label(*_shift_quarter(y, q, i)) for i in range(1, C.FORECAST_QUARTERS + 1)]


# --------------------------------------------------------------------------- codes

def _unique_codes(rng: np.random.Generator, n: int, prefix: str, digits: int) -> list[str]:
    numbers = rng.choice(10**digits - 10 ** (digits - 1), size=n, replace=False) + 10 ** (digits - 1)
    return [f"{prefix}{x}" for x in numbers]


# --------------------------------------------------------------------------- suppliers

def build_suppliers() -> pd.DataFrame:
    rows = []
    for i, (name, short, country, families) in enumerate(C.SUPPLIERS, start=1):
        rows.append({
            "supplier_id": f"S{i:03d}", "supplier_name": name, "short_name": short,
            "country": country, "currency": C.CURRENCY_BY_COUNTRY.get(country, "EUR"),
            "supplier_type": "supplier", "families": ",".join(families),
        })
    for i, (name, short, country) in enumerate(C.CONTRACT_MANUFACTURERS, start=1):
        rows.append({
            "supplier_id": f"CM{i:02d}", "supplier_name": name, "short_name": short,
            "country": country, "currency": C.CURRENCY_BY_COUNTRY.get(country, "EUR"),
            "supplier_type": "contract_manufacturer", "families": "",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- products, sales, forecast

def build_products(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (products, sales_history, forecast)."""
    n_total = C.N_EXISTING_PRODUCTS + C.N_NPD_PRODUCTS
    codes = _unique_codes(rng, n_total, "E", 5)
    types = list(C.PRODUCT_TYPES)

    products = []
    for i, code in enumerate(codes):
        ptype = types[rng.integers(len(types))]
        fmt = int(rng.choice(C.PRODUCT_TYPES[ptype]["formats"]))
        brand = C.BRANDS[rng.integers(len(C.BRANDS))]
        rng_name = C.RANGES[rng.integers(len(C.RANGES))]
        is_npd = i >= C.N_EXISTING_PRODUCTS
        products.append({
            "pf_code": code, "brand": brand, "range": rng_name, "product_type": ptype,
            "format_ml": fmt, "pf_description": f"{brand} {rng_name} {ptype} {fmt}ml",
            "is_npd": is_npd,
            "base_qty": float(rng.lognormal(np.log(40_000), 0.9)),
            "growth": float(rng.normal(0.01, 0.02)),
            "launch_index": int(rng.integers(2, 7)) if is_npd else None,
        })
    products = pd.DataFrame(products)

    # Heroes / business drivers: biggest existing products; they also grow faster.
    existing = products[~products.is_npd].sort_values("base_qty", ascending=False)
    hero_codes = set(existing.pf_code.head(C.N_HEROES))
    products["is_hero"] = products.pf_code.isin(hero_codes)
    products.loc[products.is_hero, "growth"] = rng.normal(0.035, 0.015, products.is_hero.sum())
    viral = rng.choice(sorted(hero_codes), size=4, replace=False)
    products.loc[products.pf_code.isin(viral), "growth"] = rng.uniform(0.06, 0.08, 4)
    products["is_viral"] = products.pf_code.isin(viral)
    products["stretch_factor"] = np.where(
        products.is_hero, rng.uniform(1.25, 1.5, len(products)), rng.uniform(1.15, 1.4, len(products)))

    hist_q, fc_q = history_quarters(), forecast_quarters()
    products["launch_quarter"] = products.launch_index.map(lambda i: fc_q[int(i) - 1] if pd.notna(i) else None)
    sales, forecast = [], []
    for p in products.itertuples():
        # t = 0 is the last closed quarter; history t <= 0, forecast t >= 1
        for t, quarter in zip(range(-len(hist_q) + 1, 1), hist_q):
            if p.is_npd:
                continue
            season = 1.1 if quarter.endswith("Q4") else 1.0
            qty = p.base_qty * (1 + p.growth) ** t * season * rng.normal(1, 0.05)
            sales.append({"pf_code": p.pf_code, "quarter": quarter, "qty_sold": int(round(qty))})
        for t, quarter in enumerate(fc_q, start=1):
            season = 1.1 if quarter.endswith("Q4") else 1.0
            if p.is_npd:
                if t < p.launch_index:
                    base = 0.0
                else:
                    ramp = 0.5 if t == p.launch_index else 1.0
                    base = p.base_qty * ramp * (1 + p.growth) ** (t - p.launch_index) * season
            else:
                base = p.base_qty * (1 + p.growth) ** t * season
            forecast.append({"pf_code": p.pf_code, "quarter": quarter,
                             "qty_baseline": round(base), "qty_stretch": round(base * p.stretch_factor)})

    return products, pd.DataFrame(sales), pd.DataFrame(forecast)


# --------------------------------------------------------------------------- components & BOM

_WEIGHT_G = {"plastic_bottle": 0.08, "glass_bottle": 1.6, "jar": 0.5, "jar_lid": 0.08, "tube": 0.06,
             "refill_pouch": 0.02}
_FIXED_WEIGHT_G = {"cap": 3.0, "pump": 9.0, "spray_pump": 8.0, "label": 0.5, "carton": 12.0}
_COLOURS = ["clear", "white", "black", "amber", "frosted"]


def _new_component(rng, ac_code, family, pf, is_new) -> dict:
    spec = C.FAMILIES[family]
    material = spec["materials"][rng.integers(len(spec["materials"]))]
    size = pf.format_ml if spec["sized"] else None
    neck = C.NECKS[family][rng.integers(len(C.NECKS[family]))] if family in C.NECKS else None
    canon = C.FAMILY_NAMES[family][0]
    if spec["brand_specific"]:
        desc = f"{canon} {pf.brand} {pf.range} {pf.format_ml}ml"
    elif size:
        desc = f"{canon} {material} {size}ml"
    else:
        desc = f"{canon} {material} {neck}"
    weight = (_WEIGHT_G[family] * size) if size and family in _WEIGHT_G else _FIXED_WEIGHT_G.get(family, 5.0)
    return {
        "ac_code": ac_code, "family": family, "description": desc, "material": material,
        "size_ml": size, "neck": neck,
        "colour": _COLOURS[rng.integers(len(_COLOURS))] if family not in ("label", "carton") else None,
        "weight_g": round(float(weight) * rng.uniform(0.9, 1.1), 1),
        "technology": spec["technology"],
        "brand": pf.brand if spec["brand_specific"] else None,
        "is_new": is_new,  # new component for an NPD launch, no supplier yet
    }


def build_components_and_bom(rng: np.random.Generator, products: pd.DataFrame
                             ) -> tuple[pd.DataFrame, pd.DataFrame]:
    n_slots = sum(len(C.PRODUCT_TYPES[t]["bom"]) for t in products.product_type)
    code_pool = iter(_unique_codes(rng, n_slots, "36", 7))
    components: list[dict] = []
    bom = []
    for pf in products.itertuples():
        for family in C.PRODUCT_TYPES[pf.product_type]["bom"]:
            spec = C.FAMILIES[family]
            candidates = [c for c in components
                          if c["family"] == family and not c["is_new"] and not spec["brand_specific"]
                          and (not spec["sized"] or c["size_ml"] == pf.format_ml)]
            share_p = spec["shared_prob"] * (0.5 if pf.is_npd else 1.0)
            if candidates and rng.random() < share_p:
                ac = candidates[rng.integers(len(candidates))]
            else:
                is_new = bool(pf.is_npd and not spec["brand_specific"])
                ac = _new_component(rng, next(code_pool), family, pf, is_new)
                components.append(ac)
            bom.append({"pf_code": pf.pf_code, "ac_code": ac["ac_code"], "qty_per_pf": 1})
    return pd.DataFrame(components).astype({"size_ml": "Int64"}), pd.DataFrame(bom)


# --------------------------------------------------------------------------- sourcing

def ac_demand(bom: pd.DataFrame, forecast: pd.DataFrame, column: str) -> pd.DataFrame:
    """Component demand per quarter (AC x quarter matrix) = sum over PFs of forecast x qty_per_pf."""
    merged = bom.merge(forecast, on="pf_code")
    merged["demand"] = merged[column] * merged["qty_per_pf"]
    return merged.pivot_table(index="ac_code", columns="quarter", values="demand", aggfunc="sum", fill_value=0)


def _random_date(rng, start: date, end: date) -> date:
    return start + timedelta(days=int(rng.integers(0, (end - start).days)))


def build_sourcing(rng: np.random.Generator, components: pd.DataFrame, suppliers: pd.DataFrame,
                   demand_baseline: pd.DataFrame) -> pd.DataFrame:
    """One row per AC x supplier: share, price, MOQ, lead time and contract dates (plant P100)."""
    sup = suppliers[suppliers.supplier_type == "supplier"]
    by_family = {f: sup[sup.families.str.split(",").apply(lambda fs: f in fs)] for f in C.FAMILIES}
    rows = []
    for ac in components.itertuples():
        if ac.is_new:
            continue
        spec = C.FAMILIES[ac.family]
        eligible = by_family[ac.family]
        n_sup = 2 if (spec["capacity"] and len(eligible) > 1 and rng.random() < 0.25) else 1
        chosen = eligible.sample(n=n_sup, random_state=int(rng.integers(1 << 31)))
        lo, hi = spec["price"]
        base_price = lo + (hi - lo) * rng.random()
        if not pd.isna(ac.size_ml):
            base_price *= (ac.size_ml / 250) ** 0.3
        second_share = rng.uniform(0.25, 0.4)
        avg_q = float(demand_baseline.loc[ac.ac_code].mean()) if ac.ac_code in demand_baseline.index else 0.0
        for rank, s in enumerate(chosen.itertuples()):
            share = 1.0 if n_sup == 1 else (1 - second_share if rank == 0 else second_share)
            last_rfq = _random_date(rng, date(2023, 1, 1), date(2026, 6, 30))
            start = last_rfq + timedelta(days=int(rng.integers(30, 90)))
            moq = max(5_000, int(round(avg_q * share * rng.uniform(0.1, 0.3) / 5_000)) * 5_000)
            rows.append({
                "ac_code": ac.ac_code, "supplier_id": s.supplier_id, "share": round(share, 2),
                "unit_price_eur": round(base_price * (1 if rank == 0 else rng.uniform(0.92, 1.1)), 4),
                "currency": s.currency, "price_unit": 1000 if rng.random() < 0.85 else 1,
                "moq_pcs": moq, "lead_time_days": int(rng.integers(28, 57)),
                "last_rfq_date": last_rfq, "contract_start": start, "price_valid_from": start,
                "contract_end": start + timedelta(days=3 * 365),
            })
    return pd.DataFrame(rows)


def build_std_prices(rng: np.random.Generator, sourcing: pd.DataFrame) -> pd.DataFrame:
    """Standard valuation (EUR per 1000 pcs) per AC for two fiscal years."""
    main = sourcing.sort_values("share", ascending=False).drop_duplicates("ac_code")
    rows = []
    for r in main.itertuples():
        fy26 = r.unit_price_eur * 1000 * rng.uniform(0.97, 1.06)
        rows.append({"ac_code": r.ac_code, "fiscal_year": 2026, "std_price_eur_per_1000": round(fy26, 2)})
        rows.append({"ac_code": r.ac_code, "fiscal_year": 2025,
                     "std_price_eur_per_1000": round(fy26 * rng.uniform(0.95, 1.03), 2)})
    return pd.DataFrame(rows)


_BREAKDOWN_SHARES = {  # (raw_material, conversion, decoration) ranges; rest is packaging/transport/margin
    "glass_bottle": ((0.20, 0.30), (0.35, 0.45), (0.00, 0.08)),
    "label": ((0.30, 0.45), (0.20, 0.30), (0.10, 0.20)),
    "carton": ((0.35, 0.50), (0.15, 0.25), (0.10, 0.20)),
    "pump": ((0.30, 0.40), (0.30, 0.40), (0.00, 0.05)),
    "spray_pump": ((0.30, 0.40), (0.30, 0.40), (0.00, 0.05)),
}


def build_price_breakdowns(rng: np.random.Generator, sourcing: pd.DataFrame,
                           components: pd.DataFrame) -> pd.DataFrame:
    family = components.set_index("ac_code")["family"]
    rows = []
    for r in sourcing.itertuples():
        rm, conv, deco = _BREAKDOWN_SHARES.get(family[r.ac_code], ((0.40, 0.55), (0.20, 0.30), (0.00, 0.08)))
        parts = {
            "raw_material": rng.uniform(*rm), "conversion": rng.uniform(*conv), "decoration": rng.uniform(*deco),
            "packaging": rng.uniform(0.03, 0.06), "transport": rng.uniform(0.03, 0.08),
            "overhead_margin": rng.uniform(0.08, 0.15),
        }
        total_share = sum(parts.values())
        price_1000 = r.unit_price_eur * 1000
        row = {"ac_code": r.ac_code, "supplier_id": r.supplier_id}
        row.update({k: round(v / total_share * price_1000, 2) for k, v in parts.items()})
        row["total_eur_per_1000"] = round(sum(row[k] for k in parts), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def build_fx(rng: np.random.Generator, quarters: list[str]) -> pd.DataFrame:
    rows = []
    for cur, rate in C.FX_TO_EUR.items():
        r = rate
        for q in quarters:
            if cur != "EUR":
                r = r * rng.normal(1, 0.015)
            rows.append({"currency": cur, "quarter": q, "rate_to_eur": round(r, 4)})
    return pd.DataFrame(rows)
