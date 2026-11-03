# DBT - Data Build Table
1. RAW - we are selecting the tables we need from RAW (uncleaned data)
2. STAGING - Cleaning the data (also possible to benchmark the cleaning with the "synthtetic" data we have in this examples)
3. MARTS - combined the cleaned tables into results with analytics such as saturaion rate for instance --> the math we need. 

## Project structure
- **dbt_project.yml**: The core configuration file at the root of the project that defines the project name, version, folder paths, and global materialization rules.
- **models/** directory: Contains your SQL and Python transformation files that turn raw data into clean, analysis-ready tables or views.
- **tests/** directory: Holds data quality tests (such as uniqueness and non-null checks) for your models.
- **seeds/** directory: Stores small CSV files that you can version-control and load directly into your warehouse.
- **macros/** directory: Reusable snippets of Jinja and SQL code to standardize logic across transformations.
- **snapshots/** directory: Tracks changes over time for slowly changing dimensions (SCDs).
- **profiles.yml**: External configuration file (usually stored in your home directory) that handles database connection details.

## Run it
From the `dbt/` folder (the database must be running, see `data/README.md`):
```bash
../.venv/bin/dbt build --profiles-dir .   # seeds, models and tests, in dependency order
../.venv/bin/dbt build --profiles-dir . --select fct_saturation+   # one model and its tests
../.venv/bin/dbt docs generate --profiles-dir .                     # build the docs site (models, columns, tests, lineage)
../.venv/bin/dbt docs serve --profiles-dir . --port 8081            # open it at http://localhost:8081
```
In the docs site, the blue icon at the bottom right shows the lineage graph (raw → staging → intermediate → marts). `--port 8081` because 8080 is often taken by another dev server; any free port works.
Models land in schemas `analytics_staging`, `analytics_intermediate` and `analytics_marts`.

## What each layer handles
| Model | Cleaning |
|---|---|
| `stg_finance_forecast` | trims codes, casts quantities; a blank stretch is filled with baseline x the PF's stretch uplift (`is_stretch_imputed` = true) |
| `stg_site_bom_moq` | strips spaces / `.0` from codes, maps supplier names to one canonical name (`seeds/supplier_alias_map.csv`) |
| `stg_buyer_capacity` | kpcs -> pcs, Y/yes/N/no -> boolean, canonical supplier and CM names |
| `stg_site_production` | trims codes, casts quantities |
| `stg_npd_projects` | trims codes, Y/N -> boolean |
| `stg_finance_fx_rates` | casts rates (1 unit of currency = `rate_to_eur` EUR) |
| `stg_erp_pir` | price -> EUR per piece (`price_unit` + FX rate of the snapshot quarter), `X` -> `is_deleted`, canonical supplier |
| `stg_finance_sales_history` | PF codes trimmed + uppercased, exact duplicate rows dropped, format (`0,5 L`, `500ML`) -> `format_ml` |
| `stg_finance_std_cost` | `.0` dropped from codes, EUR/1000 -> EUR per piece; a blank price takes the other fiscal year's (`is_std_price_imputed`) |
| `stg_price_breakdown` | EUR per piece; total = sum of cost lines, the stated total is kept and gaps flagged (`is_total_inconsistent`) |
| `stg_component_master` | trims, casts size/weight, lowercases colour/status |
| `stg_sourcing_contracts` | casts dates, canonical supplier |
| `int_bom` | plant BOM + NPD BOMs (new products aren't in the plant BOM until they launch) |
| `int_line_capacity` | flags capacity typed as a **monthly** figure (production above it in most past quarters) and x3 it |
| `fct_saturation` | demand per AC vs baseline capacity, and vs stretch capacity (+ qualified CMs only) |

New supplier spelling? Add a lowercase row to `seeds/supplier_alias_map.csv`. The `not_null` tests on `supplier`, prices and units (`models/staging/_staging.yml`) fail when raw data brings a spelling, currency or unit the rules don't know yet.

**Not handled in staging** (they need other sources, so they belong in intermediate models / the analyst agent): x10 price typos and expired PIRs in `erp_pir`, PIR vs site MOQ conflicts, component brand/size/material missing in `component_master` (recoverable via BOM -> PF), missing quarters in `site_production`.
