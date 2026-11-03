# Semantic layer (Cube)

This folder holds the **semantic layer**: the list of official business metrics (saturation, capacity, demand...) and how each one is calculated. It runs on [Cube](https://cube.dev/docs) (open source, in Docker).

## Why have a semantic layer?

Without it, everyone who needs "stretch saturation" writes their own SQL, and sooner or later two people (or two agents) get two different numbers. With it, each metric is defined **once**, here, and everything else asks for it **by name**:

```
raw  →  dbt (cleaning)  →  analytics_marts.fct_saturation  →  Cube  →  you / Playground / agents
                            (a table in Postgres)              (this folder)
```

You ask: *"`saturation.stretch_saturation` per `ac_code`"*. Cube writes the SQL, runs it on Postgres and returns the numbers. The agents (through `semantic-mcp`, later) only ever talk to Cube, never to the tables directly.

## Words you'll see

| Word | Meaning | Example here |
|---|---|---|
| **Cube** | A group of metrics built on one table (like a Looker *view*) | `saturation` |
| **Measure** | A number you calculate: a sum, a ratio, a max... | `baseline_capacity`, `stretch_saturation` |
| **Dimension** | Something you group or filter by | `ac_code`, `forecast_quarter` |
| **Snapshot** | The quarterly data extract the numbers come from | `2026Q3`, `2026Q4` |

A query is always: **which measures**, **grouped by which dimensions**, **filtered how**.

## Folder layout

```
semantic/
├── README.md              ← this file
├── model/cubes/           ← the metric definitions (YAML). Cube reads everything here.
│   ├── saturation.yml       ← saturation per component and quarter (mart fct_saturation)
│   └── capacity_breach.yml  ← severity, first breach, shortfall per component (mart fct_quarters_to_breach)
├── queries/               ← example queries (JSON) you can run with query.py
├── cube_client.py         ← the connection to Cube (token + request), used by query.py and the agents
├── query.py               ← run a query from the terminal
└── .cubestore/            ← Cube's local cache. Created automatically, gitignored, ignore it.
```

## The two cubes

Both are built on the same dbt table, `analytics_marts.fct_saturation`. It has one row per **snapshot × component × forecast quarter**.

| Cube | Contains | Use it for |
|---|---|---|
| `saturation` | **Latest snapshot only** | Almost everything: "which components are saturated?" |
| `saturation_history` | **All snapshots** | Comparing quarters: "did this component get better between Q3 and Q4?" |

⚠️ With `saturation_history`, always group or filter by `snapshot_quarter`. Otherwise the 2026Q3 and 2026Q4 rows are added together and the capacity looks twice as big. That's the whole reason `saturation` (latest only) exists.

### The breach cubes (`capacity_breach.yml`)

Built on `analytics_marts.fct_quarters_to_breach`, **one row per snapshot × component**. Same pattern: `capacity_breach` = latest snapshot, `capacity_breach_history` = all snapshots.

| Member | Type | What it is |
|---|---|---|
| `severity` | dimension | `none`, `temporary_spike`, `medium` (qualified CMs can absorb it), `high` (even all qualified CMs are not enough), `early_warning` (breach 5+ quarters away) |
| `recommended_action` | dimension | What a sourcer should do for that severity |
| `first_breach_quarter` / `first_critical_quarter` | dimension | First quarter with baseline saturation above 0.85 / above 1.0 |
| `quarters_to_breach` | dimension | Quarters from the snapshot to the first breach (1 = next quarter) |
| `n_quarters_baseline_over` / `n_quarters_stretch_over` | dimension | Quarters above 0.85 |
| `peak_baseline_saturation` / `peak_stretch_saturation` | measure | Worst quarter |
| `peak_baseline_shortfall` / `peak_stretch_shortfall` | measure | Pieces per quarter that can't be made, worst quarter |
| `component_count` | measure | Number of components |

⚠️ `severity` is **not** about how high the saturation is: a component at 160% baseline is `medium` when the qualified CMs can absorb it. The severity is calculated in dbt; agents only read it.

## Metrics

| Measure | What it is |
|---|---|
| `forecast_demand_baseline` / `forecast_demand_stretch` | Demand in pieces: product forecast × quantity per product (BOM) |
| `baseline_capacity` | Capacity in pieces of the lines in use today, **without** CMs |
| `stretch_capacity` | Baseline capacity **plus** CMs that are available **and qualified** for the component |
| `baseline_saturation` | baseline demand ÷ baseline capacity |
| `stretch_saturation` | stretch demand ÷ stretch capacity |
| `baseline_qty_on_stretch_capacity` / `stretch_qty_on_baseline_capacity` | The two cross-cases, for the full 2×2 matrix |
| `peak_baseline_saturation` / `peak_stretch_saturation` | The **worst single quarter** in what you selected |

**Reading the numbers:** saturation is a ratio. `0.85` = 85% of capacity used (warning), `1.0` = 100% (critical: demand ≥ capacity), `1.5` = demand is 50% above capacity.

**Ratio vs peak, which to use?** Grouped by `ac_code` + `forecast_quarter`, they're the same number. Grouped by `ac_code` only:
- `baseline_saturation` = total demand ÷ total capacity over the 3 years, i.e. the *average load*.
- `peak_baseline_saturation` = the *worst quarter*. This is the one that tells you about a bottleneck.

## Using it

### 1. Start it

Postgres must be running and dbt must have been built (`dbt build`), because Cube reads the dbt tables.

```bash
docker compose up -d cube     # starts Postgres too if needed
docker compose ps             # both containers should be "Up"
```

### 2. The Playground (easiest way to start)

Open **http://localhost:4000** in your browser.

1. Click **Measures** and pick e.g. `Saturation Peak Stretch Saturation`.
2. Click **Dimensions** and pick `Saturation Ac Code`.
3. Click **Run**. You get a table, and you can switch to a chart.
4. Click **Generated SQL** to see the SQL Cube wrote for you. It's a good way to learn.
5. Click **JSON Query** to see the same question as JSON. Copy it into a file in `queries/` to save it.

### 3. From the terminal

```bash
python semantic/query.py --meta                                     # list every measure and dimension
python semantic/query.py semantic/queries/top_saturated.json        # 10 most saturated components
python semantic/query.py semantic/queries/component_by_quarter.json # one component, quarter by quarter
python semantic/query.py semantic/queries/compare_snapshots.json    # one component, 2026Q3 vs 2026Q4
```

(Use the venv's Python, e.g. `.venv/bin/python`, if `python` isn't found.)

A query file looks like this:

```json
{
  "measures": ["saturation.peak_stretch_saturation"],
  "dimensions": ["saturation.ac_code"],
  "filters": [{"member": "saturation.ac_code", "operator": "equals", "values": ["366413968"]}],
  "order": {"saturation.peak_stretch_saturation": "desc"},
  "limit": 10
}
```

Names are always `cube.member`. Other useful filter operators: `notEquals`, `gt`, `lt`, `contains`, `set`.

**Why a script, and not plain `curl`?** The Cube API asks for a token on each request (a JWT signed with `CUBEJS_API_SECRET` from `.env`). `cube_client.py` makes that token for you.

### 4. From Python (what the agents use)

`cube_client.py` has two functions that return data instead of printing it:

```python
from semantic.cube_client import get_meta, load    # run from the repo root (python -m ...)

get_meta()   # every cube, measure and dimension, with descriptions
load({"measures": ["saturation.peak_baseline_saturation"],
      "dimensions": ["saturation.ac_code"], "limit": 5})
# → [{"saturation.ac_code": "361004668", "saturation.peak_baseline_saturation": "1.9502"}, ...]
```

Numbers come back as text (`"1.9502"`); use `float(...)` to calculate with them. The agent's tools in `pipeline/tools/cube.py` are built on these two functions (see `pipeline/README.md`). The tests for this layer are in `tests/test_saturation_cube.py` (see `tests/README.md`).

## Changing or adding a metric

1. Edit `model/cubes/saturation.yml`, or add a new `.yml` file next to it.
2. Save. In dev mode Cube reloads by itself, no restart needed.
3. Check it in the Playground, or with `python semantic/query.py --meta`.

Rules to keep the numbers right:
- **Ratios are `sum ÷ sum`**, built from other measures (`{forecast_demand_baseline} / NULLIF({baseline_capacity}, 0)`). Never use `avg` of a ratio column, because it gives wrong results when you group by fewer dimensions.
- **Logic belongs in dbt, not here.** Cleaning, joins and unit conversion go in the dbt models. Cube only says how to *add up* what dbt produced.
- **Give every measure a `description`.** The agents will read these descriptions to decide which metric to use.
- **A new metric often needs a new dbt table first.** For example, `spend` needs a purchasing mart; after that, a new cube file on top of it.

## Troubleshooting

| Problem | Fix |
|---|---|
| Playground doesn't open | `docker compose ps`. If `cube` isn't Up, check `docker compose logs cube`. |
| `relation "analytics_marts.fct_saturation" does not exist` | dbt hasn't been built yet: `cd dbt && dbt build`. |
| Numbers didn't change after editing dbt | Run `dbt build` (the marts are tables). Cube may also cache results for a few seconds. |
| Error after editing a `.yml` | It's usually indentation. The error is shown in the Playground and in `docker compose logs cube`. |
| `query.py`: `HTTP Error 403` | The token is wrong: `CUBEJS_API_SECRET` must be in `.env`. After changing `.env`, run `docker compose up -d cube` so Cube picks it up. |
| `query.py`: `Connection refused` | Cube isn't running: `docker compose up -d cube`. |
| Capacity looks twice too big | You used `saturation_history` without grouping/filtering by `snapshot_quarter`. Use `saturation` instead. |
