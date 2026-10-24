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
```
Models land in schemas `analytics_staging`, `analytics_intermediate` and `analytics_marts`.

## What each layer handles (saturation path)
| Model | Cleaning |
|---|---|
| `stg_finance_forecast` | trims codes, casts quantities; a blank stretch is filled with baseline x the PF's stretch uplift (`is_stretch_imputed` = true) |
| `stg_site_bom_moq` | strips spaces / `.0` from codes, maps supplier names to one canonical name (`seeds/supplier_alias_map.csv`) |
| `stg_buyer_capacity` | kpcs -> pcs, Y/yes/N/no -> boolean, canonical supplier and CM names |
| `stg_site_production` | trims codes, casts quantities |
| `stg_npd_projects` | trims codes, Y/N -> boolean |
| `int_bom` | plant BOM + NPD BOMs (new products aren't in the plant BOM until they launch) |
| `int_line_capacity` | flags capacity typed as a **monthly** figure (production above it in most past quarters) and x3 it |
| `fct_saturation` | demand per AC vs baseline capacity, and vs stretch capacity (+ qualified CMs only) |

New supplier spelling? Add a lowercase row to `seeds/supplier_alias_map.csv`.
