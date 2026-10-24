# Synthetic packaging-sourcing data

A seeded generator for a fictional packaging-sourcing world: finished products (PF), packaging components (AC), suppliers, contract manufacturers (CMs), sales, forecasts, purchasing records and capacities. It writes **messy source-system exports** (what the pipeline ingests) and a **ground truth** (what the pipeline is evaluated against), for **two consecutive quarters**:

```
data/synthetic/
├── 2026Q3/raw/  2026Q3/ground_truth/
├── 2026Q4/raw/  2026Q4/ground_truth/
└── changes_2026Q3_to_2026Q4.csv      # everything that changed between the two snapshots
```

```bash
uv venv --python 3.12 .venv && uv pip install -r requirements.txt --python .venv/bin/python
.venv/bin/python -m data_gen.generate            # writes data/synthetic/ (gitignored, reproducible)
.venv/bin/python -m pytest tests                 # checks consistency and planted cases
```

All names (brands, ranges, suppliers, CMs) are invented.

## Keys and how tables link

Every table links through one of two codes:

| Code | Format | Meaning |
|---|---|---|
| **PF code** | `E` + 5 digits (e.g. `E51663`) | Finished product, as sold |
| **AC code** | `36` + 7 digits (e.g. `366287809`) | Packaging component (bottle, pump, label…) |

```
finance_sales_history ─┐                 ┌─ erp_pir (AC × supplier × plant × validity)
finance_forecast ──────┼── PF ── site_bom_moq ── AC ──┼─ finance_std_cost
site_production ───────┘   (BOM: PF → AC)            ├─ price_breakdown, sourcing_contracts
                                                     ├─ component_master
                                                     └─ buyer_capacity_file.xlsx
```

`site_bom_moq.csv` is the bridge: with `npd_projects.csv` (same link for products not launched yet), it is the only table that holds both codes. A value missing for an AC can often be found by going **AC → PF → another table** (e.g. a component's size or brand comes from its PF's format or brand).

## Raw exports (`<quarter>/raw/`)

| File | Source system | Content | Main quirks |
|---|---|---|---|
| `finance_sales_history.csv` | Finance | PF, description, brand, **format**, business-driver flag, quarter, **qty sold**, net sales | format in ml *and* L (`0,5 L`, `500ML`), messy PF codes, duplicate rows |
| `finance_forecast.csv` | Finance | **Prospected sales** per PF × quarter (3 years): **QTY baseline**, **QTY stretch** | some stretch values missing; includes launches with no history |
| `finance_std_cost.csv` | Finance | **STD price** (EUR/1000) per AC, FY2025 and FY2026 | AC codes exported as floats (`366287809.0`), two years → filter on year, a few blanks |
| `finance_fx_rates.csv` | Finance | Quarterly rate to EUR | clean |
| `site_bom_moq.csv` | Production site | PF → AC (BOM), qty per PF, **material**, **supplier**, **MOQ** | supplier short names, some suppliers/materials missing, spaces in AC codes |
| `npd_projects.csv` | R&D / marketing | PF → AC (BOM) of new products not in the plant BOM yet, launch quarter, new-component flag | clean (no planted issues) |
| `site_production.csv` | Production site | Qty produced per PF × quarter | a few missing quarters |
| `erp_pir.csv` | ERP | **PIR**: price per AC × supplier × plant, price unit (1 or 1000), currency, validity, lead time, min order qty, deletion flag | **double filtering** needed (plant P100 + valid today + not deleted), history records, ×10 price typos, MOQ conflicts with the site, expired records |
| `sourcing_contracts.csv` | Sourcing | Contract dates, last RFQ date | supplier names without legal form |
| `price_breakdown.csv` | Sourcing | Price breakdown per AC × supplier (raw material, conversion, decoration, packaging, transport, margin) | upper-case supplier names, totals that don't add up, not all ACs covered |
| `component_master.csv` | Packaging R&D | AC description, family, **material**, size, neck, weight, technology, brand, status | missing material/size/brand (recoverable via other tables) |
| `buyer_capacity_file.xlsx` | Buyers (manual Excel) | Capacity per supplier line, CM available capacity, CM qualified | supplier typos, `pcs`/`kpcs` mix, `Y`/`yes`/`N`/`no`, **monthly figures in a quarterly column**, stale updates |

Every source names suppliers and components its own way: `Nordpack Industries SAS` (ERP), `Nordpack Industries` (contracts), `NORDPACK` (site), `Nordpak` (buyer typo); `Bottle PET 250ml` / `BTL PET 250ML` / `plastic bottle PET 250ml` / `Flacon`.

## Ground truth (`<quarter>/ground_truth/`, evals only)

| File | Content |
|---|---|
| `products.csv`, `components.csv`, `bom.csv`, `suppliers.csv` | Clean master data (hero, viral and launch flags included) |
| `sales_history.csv`, `forecast.csv` | Clean sales and forecasts |
| `sourcing.csv` | AC × supplier: share, EUR unit price, MOQ, lead time, contract dates |
| `std_prices.csv`, `price_breakdowns.csv` | Clean STD prices and price breakdowns |
| `capacity.csv`, `cm_capacity.csv` | True line capacities and CM capacity (with qualification) |
| `saturation.csv` | Baseline and stretch saturation per AC × quarter, plus the cross cases |
| `planted_cases.csv` | Planted capacity cases with expected severity and action |
| `rfq_candidates.csv` | Expected RFQ triggers: A capacity, B new product, C 3-year review |
| `supplier_aliases.csv` | Every supplier name variant used → supplier id (entity-resolution eval) |
| `issues_manifest.json` | Every injected error: table, key, column, raw value, true value, how to fix |
| `summary.json` | Counts per case and issue type |

## Planted capacity cases

| Case | What the pipeline should conclude |
|---|---|
| `both_saturated` | **High**: even with qualified CMs the stretch scenario can't be produced → RFQ / investment |
| `baseline_only` | **Medium**: CMs absorb it short term, no buffer left |
| `future_breach` | **Early warning**: baseline threshold crossed in ~2 years → plan ahead |
| `cm_not_qualified` (trap) | **High**: looks medium if the unqualified CM is counted |
| `single_quarter_spike` (decoy) | **No RFQ**: one-off forecast peak, manage with stock build or CM |
| `monthly_capacity_entry` (decoy) | **None**: looks saturated only because the buyer typed a monthly capacity |

Thresholds: warn 85%, critical 100% (`config.py`).

## From one quarter to the next

The 2026Q4 snapshot is the 2026Q3 world one quarter later:

| Change | What happens |
|---|---|
| Quarter closed | 2026Q4 actuals added (viral products overshoot), oldest quarter dropped (8-quarter window) |
| New forecast | Version `FC_2026Q4`: every PF revised (±4%, viral +10–20%), horizon now 2027Q1–2029Q4 |
| `capacity_added` | A supplier added a mould: one `baseline_only` AC is no longer saturated |
| `capacity_reduced` | A supplier reallocated a line: a healthy hero AC becomes saturated |
| `cm_qualified` | A CM got qualified: one `cm_not_qualified` AC drops from high to medium |
| `buyer_fixed_entry` | The buyer corrected one of the monthly capacity entries |
| `price_change` | New PIR records (raw-material index increase) for ~10% of AC × supplier |
| `rfq_completed` | Two 3-year reviews closed with a new contract and a lower price |

All of these, plus every resulting severity change, are listed in `changes_2026Q3_to_2026Q4.csv`. Random data errors are re-drawn in each snapshot (as when a new extract is pulled); the naming conventions of each system stay the same.

## Simplifications (to revisit)
- Capacity is modelled per AC × supplier (one dedicated line/mould); shared lines and moulds are not modelled yet.
- No investment options table yet (mould cost, capacity added, lead time, budget cap).
