# Tests

Automated checks, run with **pytest** from the **repo root**. They are free (no LLM calls). The LLM evals of the agents live in `evals/` (see `evals/README.md`).

## Run them

```bash
pytest                                                      # everything in tests/
pytest tests/test_saturation_cube.py tests/test_breach_cube.py tests/test_dims_cube.py tests/test_volume_at_risk_cube.py tests/test_cube_tools.py   # only the marts, Cube and tools (~3 s)
pytest tests/test_data_gen.py                               # only the synthetic data generator
pytest -k timeline                                          # only tests whose name contains "timeline"
pytest -v                                                   # one line per test, with its name
```

(Activate the venv first, `source .venv/bin/activate`, or use `.venv/bin/python -m pytest`.)

**Before running the Cube tests:** Docker up, data loaded, dbt built:
```bash
docker compose up -d
```
If there is no generated data or Cube isn't reachable, those tests are **skipped** (shown as `s`), not failed. Run `pytest -rs` to see why they were skipped.

## What is tested where

| Layer | Tested by | Checks |
|---|---|---|
| Synthetic data | `tests/test_data_gen.py` | The generator: code formats, planted issues, snapshots |
| dbt models + marts | `dbt build` (in `dbt/`) | Grain, not-null, accepted-values and relationships tests (`_staging.yml`, `_marts.yml`); `fct_saturation` row by row, `fct_quarters_to_breach` per planted case, `dim_product` and `dim_component` per row vs the ground truth (`dbt/tests/`) |
| Cube (on the marts) | `tests/test_saturation_cube.py`, `tests/test_breach_cube.py`, `tests/test_dims_cube.py`, `tests/test_volume_at_risk_cube.py` | See below |
| Agent tools | `tests/test_cube_tools.py` | See below |
| The agent itself (LLM) | `evals/` | Does it label the planted cases right? |

### `test_saturation_cube.py`: the saturation mart through Cube

| Test | Checks |
|---|---|
| `..._holds_only_the_latest_snapshot` | The `saturation` cube shows only the newest snapshot |
| `..._holds_every_snapshot` | `saturation_history` has all snapshots |
| `..._per_quarter_matches_ground_truth` | Baseline and stretch saturation, every component × quarter, both snapshots, within 0.005 |
| `..._total_demand_over_total_capacity` | Over several quarters Cube divides totals (sum ÷ sum), never averages ratios |
| `test_peaks_match_planted_cases` | Worst-quarter values match `planted_cases.csv` |
| `..._reproduce_from_cube` | The generator's severity rule applied to Cube's numbers gives exactly the planted labels. If this passes but the agent is wrong, the agent is the problem, not the data. |

### `test_breach_cube.py`: the breach mart through Cube

`capacity_breach` holds only the latest snapshot and one row per component; severity, first breach and peaks match `planted_cases.csv` in every snapshot; `quarters_to_breach` counts from the snapshot (next quarter = 1); peaks agree with the `saturation` cube.

### `test_dims_cube.py`: the component and product cubes

`component`, `product` and `product_component` hold only the latest snapshot; every component once; brand, material, size, `is_new`, `n_products_using` and `used_by_hero` match `components.csv` + `bom.csv` + `products.csv` in every snapshot; products match `products.csv`; `product_component` is exactly `bom.csv`. **The joins:** grouping saturation by `component.family`, `used_by_hero` or `material` keeps the total (per snapshot for the history cubes), so no join doubles rows.

### `test_volume_at_risk_cube.py`: what shortfalls cost

Recalculates the whole allocation in pandas from `saturation.csv`, `forecast.csv` and `bom.csv` and compares with Cube: units per component, units per product (largest component share, not the sum), the planted case (AC 366413968 short 119,810 pieces in 2029Q4). Euros: revenue = units × price, launches have no euros, contribution < revenue. Joins to component / product / breach keep the totals.

### `test_cube_tools.py`: the agent's tools

Each named tool returns what it promises (sorted worst first, right number of rows, every quarter in order, every snapshot); unknown scenarios are rejected; an unknown component returns no rows; `query_metric` rejects made-up measure, dimension and filter names. `get_component_info` lists exactly the products of the truth BOM with the right hero flags; `get_products_at_risk` returns exactly the product × component pairs on a high / medium / early-warning breach (and only heroes / only high when asked); breach tools say what the component is.

## Where the expected answers come from

`tests/ground_truth.py` reads the ground truth the generator wrote to `data/synthetic/<snapshot>/ground_truth/` (`saturation.csv`, `planted_cases.csv`, ...). After regenerating the data, reload and rebuild before testing:

```bash
python -m data_gen.generate && python loader/load_raw.py && (cd dbt && dbt build --profiles-dir .)
```

## Shared setup (repo root)

| File | Does |
|---|---|
| `pytest.ini` | Puts the repo root on the import path; `pytest` alone runs `tests/` only; registers the `llm` marker |
| `conftest.py` | The `cube` fixture (skips when data or Cube is missing) and the `--run-llm` option for the evals |

## Adding tests for a new mart

1. Build and test the mart in dbt first (`_marts.yml` + a ground-truth test in `dbt/tests/`).
2. Add its cube, then a `tests/test_<mart>_cube.py` in the same style as `test_saturation_cube.py`: start with `pytestmark = pytest.mark.usefixtures("cube")`, query with `semantic.cube_client.load`, compare with `ground_truth(...)`.
3. Every new named tool gets a test in `test_cube_tools.py`.
4. New agent questions go into `evals/`.
