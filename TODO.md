# TODO

What to build next, in order, and how. Status on 2026-11-03: stage 1 trigger A (capacity) works end to end: `fct_saturation` + `fct_quarters_to_breach` → Cube → agent tools → Streamlit chat, eval 16/16.

Tick a box when it's done. Each mart follows **the recipe** below, so the per-item sections only list what's specific to that mart.

---

## The recipe (every new mart)

The principle: **numbers and rules in code (dbt/Cube), language and judgement in the LLM.** If you can write it as a formula or rule, it goes in dbt. The agent only reads the result and explains it.

1. **Define it on paper**: the question it answers, the **grain** (one row per what?), every column with its formula, and the decisions it depends on.
2. **Intermediate model(s)** in `dbt/models/intermediate/` if you combine or correct several sources and the result is reusable.
3. **Mart** `dbt/models/marts/<name>.sql`, same shape as `fct_quarters_to_breach.sql`: comment header with question + grain + rules, imports via `ref()`, one CTE per idea, a unique key column (`<name>_key`) for Cube. Thresholds and parameters go in `vars:` in `dbt_project.yml`, not hard-coded.
4. **dbt tests**: in `_marts.yml` (unique + not_null on the key, `accepted_values` on labels, not_null on what must always exist) and a singular test `dbt/tests/assert_<name>_matches_ground_truth.sql` that returns only wrong rows. Add the ground-truth table to `models/staging/_sources.yml` if it isn't there yet.
5. **Build**: `cd dbt && dbt build --profiles-dir . --select +<name>+`
6. **Cube**: `semantic/model/cubes/<name>.yml`, a `<name>_history` cube (all snapshots) + a `<name>` cube that `extends` it with the latest-snapshot filter. Every member gets a `description` (the agent reads them). Ratios are `sum ÷ sum` measures, never `avg`. Check with `python semantic/query.py --meta`.
7. **Cube tests**: `tests/test_<name>_cube.py`, copy `tests/test_breach_cube.py`: latest-only filter, one row per grain, values vs the ground truth.
8. **Named tool(s)** in `pipeline/tools/cube.py`: fixed query, only the changing values as parameters, a docstring that says when to use it. Add to `CUBE_TOOLS`. Test it in `tests/test_cube_tools.py`.
9. **Agent**: tell the prompt (`pipeline/agents/analyst.py`) what the new labels/numbers mean and that it must read them, never calculate them.
10. **Eval**: questions in `evals/` with a machine-readable `RESULT:` line compared with the ground truth. Run `pytest evals --run-llm` before and after.
11. **Docs**: `dbt/README.md` (model table), `semantic/README.md` (cube section), `pipeline/README.md` (tool table, score), `tests/README.md`, `evals/README.md`.

---

## Decisions to make first

| # | Decision | Needed for | Suggested default |
|---|---|---|---|
| D1 | When a component is short, which finished products (PF) lose volume? | 2 | Proportionally to each PF's forecast. Alternative: protect hero products first. |
| D2 | Selling price per PF | 2 | `net_sales_eur ÷ qty_sold` over the last 4 history quarters |
| D3 | Cost: there is **no full production cost** in the data | 2 | Report **revenue at risk** + **contribution before other costs** (price − packaging cost from std cost × BOM), clearly labelled |
| D4 | Which spend volume: next 4 forecast quarters (baseline) or last 4 quarters of production? | 4 | Next 4 forecast quarters, baseline |
| D5 | Priority score weights | 6 | Start with simple, explainable rules (below); tune with the eval |
| D6 | Investment / CM / RFQ option data (costs, lead times, budget cap) | 7 | Extend the generator with realistic ranges per component family |

---

## 0. Housekeeping (quick)

- [ ] **Delete the empty `__init__.py` files in `dbt/`** (`dbt/__init__.py`, `dbt/models/__init__.py`, `dbt/tests/__init__.py`). dbt shows `dbt/models/__init__.py` as a fake model called `__init__`, and a root folder named `dbt` with an `__init__.py` can hide the real `dbt` package from Python run at the repo root. Then `dbt build` → same result (72 passed).
- [ ] **`.env.example`** with every key and placeholder values (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `CUBEJS_API_SECRET`, `OPENAI_API_KEY`, `OPENAI_MODEL`), commit it, and mention `cp .env.example .env` in the README Getting started table.
- [ ] **Merge `dbt-saturation` into `main`** (via a pull request) once the above is in.

---

## 1. `dim_component` + `dim_product` (descriptive dimensions)

**Why:** every later cube benefits from grouping and filtering by what a component or product *is*: "saturation by family", "only hero products", "spend per material". Also needed for prices (2) and hero weighting (6).

**Grain:** `dim_component` = snapshot × `ac_code`; `dim_product` = snapshot × `pf_code`.

**Inputs and logic**
- `dim_component` from `stg_component_master`: family, description, material, size_ml, neck, colour, weight_g, technology, brand, status, `is_new`.
  - **Cross-source fix (planted: 32 `missing_recoverable` values in `component_master`)**: when brand / size / material is blank, recover it via the BOM → the PFs that use the component → their brand/format. Do this in an intermediate model `int_component_enriched` and add `is_<field>_recovered` flags.
  - Add `n_products_using` (count of PFs in `int_bom`) and `used_by_hero` (any of them a hero).
- `dim_product` from `stg_finance_sales_history` (latest description, brand, format_ml, `is_business_driver` = **hero**) + `stg_npd_projects` (`is_npd`, `launch_quarter` for products not on sale yet).

**Tests:** vs `ground_truth.components` (family, material, brand, size_ml, is_new) and `ground_truth.products` (brand, format_ml, is_hero, is_npd, launch_quarter). Add both tables to `_sources.yml`.

**Cube:** `component` and `product` cubes, and **joins** from `saturation`, `capacity_breach` (and later cubes) to them, on **both** keys because the dims are per snapshot:
```yaml
joins:
  - name: component
    relationship: many_to_one
    sql: "{CUBE}.ac_code = {component.ac_code} AND {CUBE}.snapshot_quarter = {component.snapshot_quarter}"
```
Then `saturation.peak_baseline_saturation` grouped by `component.family` works.

**Tool / agent:** `get_component_info(ac_code)` (what it is, which products use it, hero or not). Extend `get_capacity_breaches` with family and `used_by_hero`.

**Done when:** dbt tests pass vs both ground-truth tables; you can group saturation by `component.family` in the Playground.

### Step-by-step guide (where to look, no code)

- [x] **Step 1: Understand the data** (DBeaver). Done on 2026-11-03. What the data shows:
  - `ground_truth.components`: 165 components in 2026Q4; `brand` is empty for 61 of them **in the truth itself**, so a blank brand is often correct (generic components).
  - `issues_manifest.json` (search `component_master.csv`) gives the recovery rules in `how_to_fix`: **Brand** (15 missing): AC → PF via the BOM, then brand from sales history. **Material** (13): directly from `site_bom_moq` via the AC code. **Size** (4): AC → PF via the BOM, then the PF format from sales history.
  - `ground_truth.products`: 76 products, 20 heroes, 6 NPD. Hero = `Business Driver` in `finance_sales_history`. NPD products have no sales history.
  - The trap: a component used by products of **two different brands**. Check what the truth does for those.

- [ ] **Step 2: Build `dim_product` first (not `dim_component`).** `dim_component` needs to know whether a component is used by a **hero** product, so the product dimension has to exist first.
  - **Grain:** snapshot × `pf_code`. That means **two** sources stacked: products on sale (sales history) **plus** NPD products not yet on sale.
  - **Where to look for examples:**
    - `dbt/models/intermediate/int_bom.sql`: stacking two sources with `union all`, and "take it from source A only if it's not already in source B" (`not exists`). It's exactly the same situation.
    - `dbt/models/staging/stg_finance_sales_history.sql`: sales history has **one row per quarter**, but you need **one row per product**. The `row_number()` dedup pattern there is how to keep one row (e.g. the latest quarter).
  - **Decide:** which quarter's description and brand do you keep if they differ? (Latest is the usual choice.)
  - **Put it in** `models/marts/`. Dimensions are marts too (in dbt, often prefixed `dim_` instead of `fct_`).

- [ ] **Step 3: Recover the missing component fields (`int_component_enriched`).** This is the cross-source part, so it goes in `models/intermediate/`.
  - **Where to look:**
    - `stg_finance_std_cost.sql`: "fill a blank from another place" with `coalesce`, plus an `is_..._imputed` flag. Copy that idea for `is_brand_recovered` etc.
    - `stg_finance_forecast.sql`: the same idea, using a CTE that's joined back in.
    - `int_bom.sql` / `int_line_capacity.sql`: joining staging models with `snapshot_quarter` **always** in the join condition (the dual condition).
  - **One CTE per recovery rule** (brand via BOM + product, material via BOM, size via BOM + product format), then one final select with `coalesce(original, recovered)`.
  - **Only recover when the answer is unambiguous.** If the products using a component disagree on brand, leave it null (`count(distinct ...) = 1` is the kind of check that helps).
  - Try each CTE as a query in DBeaver first; copy it into the dbt file once the rows look right.

- [ ] **Step 4: `dim_component` (mart).** `int_component_enriched` plus a few useful columns:
  - `n_products_using`: count over `int_bom` (look at how `fct_saturation.sql` groups and counts).
  - `used_by_hero`: does any product using it have the hero flag? (`bool_or` in Postgres is handy; look it up.)
  - `is_new`: already in `stg_npd_projects` (`is_new_component`).

- [ ] **Step 5: Tests.**
  - **Add the two ground-truth tables** (`components`, `products`) to `dbt/models/staging/_sources.yml` under `ground_truth` (look at how `planted_cases` was added).
  - **Generic tests** in `_marts.yml`: unique + not_null on a key, as for `fct_quarters_to_breach`.
  - **Singular tests:** copy `dbt/tests/assert_breach_matches_planted_cases.sql`, one test per dim, returning the rows where your value ≠ the truth.
  - **⚠️ Gotcha:** the ground-truth tables in Postgres are **all text** (the loader loads everything as text): booleans arrive as `'True'`/`'False'`, sizes as `'500'` or `'500.0'`, and "empty" might be `''` rather than null. Look at how the breach test uses `nullif(..., '')` and `is distinct from`; you'll need the same care, plus casts.
  - **Run:** `cd dbt && dbt build --profiles-dir . --select +dim_product+ +dim_component+`
  - **When a test fails:** run the test's SQL yourself in DBeaver (dbt writes the compiled SQL to `dbt/target/compiled/...`) and look at the wrong rows. They usually point straight at the rule you got wrong, especially the brand trap.

- [ ] **Step 6: Cube** (once dbt is green).
  - **Two new cube files**, `component.yml` and `product.yml`: copy the structure of `capacity_breach.yml`, but with **only dimensions** plus a `count` measure.
  - **Joins:** add a `joins:` block to `saturation.yml` and `capacity_breach.yml` (the YAML is above, under **Cube**). Read Cube's docs page **"Joins"** (data modeling → joins) to understand `many_to_one`. Join on **both** `ac_code` and `snapshot_quarter`.
  - **Check** in the Playground (http://localhost:4000): `Saturation Peak Baseline Saturation` grouped by `Component Family`. If the numbers look doubled, the join is missing the snapshot condition.

- [ ] **Step 7: Python tests + the tool**, following the recipe (steps 7–11 at the top): `tests/test_dims_cube.py`, `get_component_info(ac_code)` in `pipeline/tools/cube.py`, a test in `tests/test_cube_tools.py`, then the docs.

---

## 2. `fct_volume_at_risk` (the finance case)

**Question:** *"If I don't invest and don't use CMs, how many products can't I make, and what is that worth?"*

**Grain:** snapshot × `ac_code` × `pf_code` × `forecast_quarter` (summarise per AC and per PF in Cube).

**Logic** (with defaults D1–D3)
1. **Component shortfall per quarter** (not just the peak), from `fct_saturation`, without CMs = on baseline capacity:
   - `shortfall_baseline = greatest(qty_baseline − baseline_capacity, 0)`
   - `shortfall_stretch_no_cm = greatest(qty_stretch − baseline_capacity, 0)` (the cross case: high demand, no CM)
2. **Split over the products that use the component** (D1): each PF's share = its demand for this AC ÷ total demand for this AC (forecast × `qty_per_pf`, from `int_bom` + `stg_finance_forecast`).
3. **Pieces → products**: `pf_units_lost = shortfall × pf_share ÷ qty_per_pf`.
4. **Price** (D2) in an intermediate `int_pf_price`: `sum(net_sales_eur) ÷ sum(qty_sold)` over the last 4 history quarters. NPD products have no sales history → price is null, flag `has_price = false`, never guess.
5. **Cost** (D3) in an intermediate `int_pf_packaging_cost`: `sum(std_price_eur_per_piece × qty_per_pf)` over the PF's BOM.
6. `revenue_at_risk = pf_units_lost × price`; `contribution_at_risk = pf_units_lost × (price − packaging_cost)`.

⚠️ **Don't add up PF losses across components.** If two components of the same PF are both short, the PF loses the **larger** of the two, not the sum. In Cube, per-PF totals must take the `max` over its components per quarter. Do this in the mart as a second model `fct_product_volume_at_risk` (grain snapshot × pf_code × forecast_quarter), so Cube only sums safe rows.

**Tests:** grain unique; `pf_units_lost ≥ 0`; for each AC, `sum(pf_units_lost × qty_per_pf)` = the component shortfall (allocation adds up); spot-check one planted case by hand (e.g. AC 366413968: its shortfall in 2029Q4 was 119,810 pieces).

**Cube:** `volume_at_risk` (per AC × PF × quarter) and `product_volume_at_risk` (per PF × quarter). Measures `units_at_risk`, `revenue_at_risk`, `contribution_at_risk` (sums), dimensions joined from `product` (hero) and `component` (family). Descriptions must say "without CMs or investment" and "contribution = price − packaging cost only".

**Tool / agent:** `get_volume_at_risk(ac_code=None)` and `get_product_volume_at_risk(pf_code=None)`. Prompt: say what the numbers include and exclude; never compute euros itself.

**Eval:** "What is the revenue at risk for AC X?" for the 12 A-trigger components, compared with the mart (the mart is the truth here, after you've checked it by hand).

**Done when:** the question in your screenshot ("what are these sold for and how many can't I produce…") gets a euro answer from one tool call, with the assumptions stated.

---

## 3. `fct_contract_review` (trigger C, 3-year review)

**Question:** which supply contracts haven't been tendered for 3+ years?

**Grain:** snapshot × `ac_code` × `supplier`.

**Logic:** from `stg_sourcing_contracts`:
- **Snapshot date** = the day after the snapshot quarter ends (`2026Q3` → 2026-10-01, `2026Q4` → 2027-01-01). Add a macro `snapshot_date(col)` next to `quarter_number` in `macros/quarters.sql`.
- `years_since_last_rfq`, `contract_age_years`, `months_to_contract_end`.
- `is_review_due = last_rfq_date <= snapshot_date − 3 years` (this is exactly the generator's rule). Put `review_after_years: 3` in `vars:`.
- Join supplier names to IDs via the alias seed if you need `supplier_id` for the test (ground truth uses `S001`-style IDs: check `ground_truth.suppliers`).

**Tests:** the set of (ac_code, supplier) with `is_review_due` = the `C_review` rows of `ground_truth.rfq_candidates` (52 in 2026Q4). Add `rfq_candidates` and `suppliers` to `_sources.yml`.

**Cube:** `contract_review` with `contract_age_years`, `years_since_last_rfq`, `is_review_due`, `contract_end`.

**Tool / agent:** `get_contracts_due_for_review()`.

**Done when:** dbt test matches all 52 C-candidates in both snapshots.

---

## 4. `int_pir_current` + `fct_spend` (spend, supplier share, sole source)

**Question:** how much do we spend per component and supplier, what share does each supplier have, and which components are **sole-sourced** (a risk the priority score uses)?

### 4a. `int_pir_current`: the valid price per component × supplier

The ERP purchasing info records (PIR) contain planted traps. Logic, in this order:
1. **Filter** = plant `P100` **and** valid on the snapshot date (`valid_from ≤ date ≤ valid_to`) **and** not deleted. (Planted: 5 `double_filter_trap`: a cheaper PIR that is deleted or for another plant; 2 `expired_pir_still_used`.)
2. **Price outliers** (planted: 8 `price_outlier`, a ×10 typo): compare `price_eur_per_piece` with the same AC's std cost (`stg_finance_std_cost`) or other suppliers' prices; if it's ~10× off, divide by 10 and set `is_price_corrected`.
3. **MOQ conflict** (planted: 18 `moq_conflict`): PIR `min_order_qty` ≠ site `moq_pcs` (`stg_site_bom_moq`) → flag `has_moq_conflict` (don't silently pick one; the data-quality agent will explain it later).

Tests vs `ground_truth.sourcing` (`unit_price_eur`, `moq_pcs`, `lead_time_days`) and the `issues_manifest.json` entries for `erp_pir.csv`.

### 4b. `fct_spend`

**Grain:** snapshot × `ac_code` × `supplier`.
- **Volume** (D4): next 4 forecast quarters, baseline, per AC (from `fct_saturation.qty_baseline`).
- **Share** per supplier: first check how `ground_truth.sourcing.share` shows up in the raw data (several valid PIRs per AC? the buyer capacity file lines?). If it can't be derived, use equal shares and note it.
- `annual_spend_eur = volume × share × price`; `supplier_share` (per AC); `is_sole_source = number of valid suppliers for the AC = 1`.

**Cube:** `spend` with `spend_eur` (sum), `supplier_share` (sum ÷ sum), `is_sole_source`; joined to `component`.

**Tool / agent:** `get_spend(ac_code=None, supplier=None)`, `get_sole_source_components()`.

**Done when:** prices match `ground_truth.sourcing`, and every planted PIR issue is either corrected or flagged.

---

## 5. `fct_npd_triggers` (trigger B, new products)

**Question:** which launches need components we don't buy yet?

**Grain:** snapshot × `ac_code` × `pf_code`.

**Logic:** from `stg_npd_projects` (rows with `is_new_component = true`) joined to `dim_product.launch_quarter`; `due_quarter = launch_quarter`; `has_contract` = the AC appears in `stg_sourcing_contracts`. The generator's rule: a component flagged new in a launch BOM → trigger. Also add `npd_saturation_impact`: the extra saturation the launch causes on existing components (from `fct_saturation`, NPD rows of `int_bom` vs without them), as information, not a trigger.

**Tests:** = the `B_new_product` rows of `ground_truth.rfq_candidates` (8 in 2026Q4: ac_code, pf_code from the reason text, due).

**Cube / tool:** `npd_triggers`; `get_npd_triggers()`.

**Done when:** all 8 B-candidates found with the right launch quarter.

---

## 6. `fct_rfq_candidates` (Gate 1: one ranked list)

**Question:** of everything that could trigger an RFQ, what should the sourcer launch first?

**Grain:** snapshot × `trigger` × `ac_code` × `supplier` (supplier only for C).

**Logic:** `union all` of
- **A** from `fct_quarters_to_breach` where severity in (`high`, `medium`, `early_warning`) (**not** `temporary_spike` or `none`: the generator excludes them), `due = first_breach_quarter`;
- **B** from `fct_npd_triggers`, `due = launch_quarter`;
- **C** from `fct_contract_review` where `is_review_due`, no due quarter.

**Priority score** (D5, start simple and explainable, every part a column so the agent can explain it):
- severity points (high 3, medium 2, early_warning 1; B 2; C 1)
- urgency: `quarters_to_breach` / quarters to launch (sooner = more points)
- money: `revenue_at_risk` from (2), in bands
- hero: +1 if `used_by_hero` (1)
- sole source: +1 if `is_sole_source` (4)
- later: urgency vs the **lead time of the fix** (7)

**Tests:** the set of (trigger, ac_code, supplier, due) = `ground_truth.rfq_candidates` (72 rows in 2026Q4). The ranking has no ground truth: check it with the eval.

**Cube / tool:** `rfq_candidates` with `priority_score` and every score part; `get_rfq_candidates(top=10)`. This is what the analyst agent presents at Gate 1.

**Eval:** "Which RFQs should I launch first, and why?" → the agent's top 5 must be the mart's top 5, and every reason it gives must match a score part.

**Done when:** stage 1 of the README is complete: all three triggers in one ranked, explained list.

---

## 7. Stage 2: `fct_capacity_options` (invest vs subcontract vs RFQ)

**Question:** for each bottleneck, what are the options, what do they cost, how much capacity do they add, how long do they take, and do they fit the investment budget?

**⚠️ The data doesn't exist yet.** First extend the generator (`data_gen/`):
- per capacity component: **invest** (mould/tooling or line: cost €, capacity gained per quarter, lead time in quarters), **subcontract** (CM: price premium per piece, max capacity, qualification lead time if not qualified), **RFQ new supplier** (qualification lead time, expected price range);
- an **annual investment budget cap** in `config.py`;
- ground truth: the expected best option per planted case;
- new raw files (e.g. `capex_options.csv`, `cm_offers.csv`), loader + staging models.

Then the mart: per bottleneck × option, `option_cost`, `capacity_gained`, `lead_time_quarters`, `covers_shortfall` (vs `fct_quarters_to_breach`), `ready_before_breach` (lead time vs `quarters_to_breach`), `fits_budget`. The **recommendation** is a rule in dbt; the agent explains the trade-off.

**Done when:** each A-candidate has costed options and a recommended one matching the ground truth.

---

## Later (not marts)

- [ ] **Chart tools** for the agent and the Streamlit app: `plot_component_timeline(ac_code)` (line chart, 0.85 / 1.0 lines), `plot_breach_overview()`, later `plot_volume_at_risk()`. Data from Cube, drawing by code (Plotly); the LLM only picks the chart and writes the title. Test that chart data = Cube data.
- [ ] **Read-only "explore" SQL tool** on `analytics_marts` only, every answer labelled *exploratory, not an official number*. For one-off questions; a question that keeps coming back becomes a mart.
- [ ] **`semantic-mcp`**: move the Cube tools into an MCP server (`mcp_servers/semantic/`), same tool names and signatures, so the agent code doesn't change.
- [ ] **Graph v2** (`pipeline/graph.py`): fixed steps `fetch_candidates` (code) → `analyse` (LLM, structured Pydantic output) → `report`, instead of the free tool loop, for the Gate 1 run.
- [ ] **Data-quality report**: compare what dbt flagged (`is_*_corrected`, `has_*_conflict`, `is_*_imputed`) with `issues_manifest.json` (precision / recall per issue type), README §5.
- [ ] **Langfuse** tracing (README §6) once there are several agents.
