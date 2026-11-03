# Pipeline (agents and their tools)

This folder holds the **agents** (LangGraph) and the **tools** they use to get data. Today there is one agent, the **analyst agent**, which answers capacity-saturation questions by reading the Cube semantic layer.

```
question → analyst agent (LLM) ⇄ tools (pipeline/tools/cube.py) → Cube → analytics_marts.fct_saturation
```

The agent never writes SQL and never touches the tables. It picks a tool, the tool runs a Cube query, and the agent explains the numbers it got back.

## Folder layout

```
pipeline/
├── README.md          ← this file
├── tools/
│   └── cube.py        ← the Cube tools the agents can call
└── agents/
    └── analyst.py     ← the analyst agent (LangGraph graph + system prompt)
```

## Before you start

1. **Docker up**, with data loaded and dbt built (see `data/README.md` and `dbt/README.md`):
   ```bash
   docker compose up -d
   ```
2. **OpenAI settings in `.env`** (repo root):
   ```
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-5.4-mini      # optional; this is the default
   ```
3. **Run everything from the repo root, with `python -m`.** `-m` makes Python treat the repo root as the starting point, so `pipeline/` and `semantic/` can import each other. Running a file directly (`python pipeline/agents/analyst.py`) gives `ModuleNotFoundError`.

## Ask the agent from the terminal

```bash
python -m pipeline.agents.analyst "Which components are most saturated?"
python -m pipeline.agents.analyst "Explain what is happening with AC 366413968."
python -m pipeline.agents.analyst "What changed for AC 369576663 since the last snapshot?"
```

Every tool call is printed (`→ get_component_timeline({'ac_code': '366413968'})`) before the answer, so you can see where the numbers come from. For a chat in the browser, see `app/README.md`.

## Check the tools without an LLM

```bash
python -m pipeline.tools.cube
```

This runs each tool once against Cube and prints the rows. It costs nothing and is the quickest way to see if Cube is reachable.

## The tools (`tools/cube.py`)

**Named tools** answer the common questions with a **fixed query**. The LLM only picks the parameters, so the same question always runs the same query.

| Tool | Answers | Cube |
|---|---|---|
| `get_capacity_breaches()` | Every component with a capacity problem: severity, first breach, quarters to breach, action, shortfall. Soonest first. | `capacity_breach` |
| `get_component_breach(ac_code)` | The same for one component | `capacity_breach` |
| `get_top_saturated(scenario, limit)` | Which components are most saturated (worst quarter), worst first? `scenario` is `baseline` or `stretch`. | `saturation` |
| `get_component_timeline(ac_code)` | One component quarter by quarter: demand, capacity, saturation | `saturation` |
| `compare_snapshots(ac_code)` | One component across data snapshots (e.g. 2026Q3 vs 2026Q4) | `saturation_history` |

**Generic fallback**, for questions no named tool covers:

| Tool | Does |
|---|---|
| `list_metrics()` | Lists every cube, measure and dimension with its description |
| `query_metric(measures, dimensions, filters, order, limit)` | Runs any Cube query. Names are checked against Cube first; unknown names return an error message the agent can correct itself from. |

The **docstring** of each tool is what the LLM reads to decide when to use it, so keep it accurate.

### Adding a tool

1. Write a function in `tools/cube.py` with a fixed query and only the changing values as parameters. Use `Literal[...]` for parameters with a fixed set of values.
2. Put `@tool` above it and write a clear docstring: what it answers, when to use it.
3. Add it to `CUBE_TOOLS` at the bottom of the file. The agent picks it up automatically.
4. Add a test in `tests/test_cube_tools.py`.

Keep tools **thin**: they choose a query, nothing more. Calculations belong in dbt (the marts) or Cube (the measures), never in Python here.

## The analyst agent (`agents/analyst.py`)

A LangGraph graph with two nodes in a loop:

```
          ┌──────────────┐   wants a tool    ┌──────────────┐
question →│  agent (LLM) │ ────────────────► │  tools node  │ → runs the tool on Cube
          │              │ ◄──────────────── │ (CUBE_TOOLS) │
          └──────┬───────┘   tool results    └──────────────┘
                 │ no more tools needed
                 ▼
               answer
```

- **`SYSTEM_PROMPT`**: the role, the saturation definitions and **what each severity label means** for a sourcer (with its action). The agent does **not** calculate severity: it reads it from the breach tools, which get it from the dbt mart `fct_quarters_to_breach`. Numbers in code, explanation by the LLM.
- **`build_graph()`**: builds the graph above.
- **`run(history)`**: runs the agent on a whole conversation and yields each tool call, then the answer. The Streamlit app uses this.
- **`ask(question)`**: one question in, answer out. Used by the terminal command and the evals.

To try another model, change `OPENAI_MODEL` in `.env`. No code change needed.

## How good is it?

Measure it with the eval (costs API calls, see `evals/README.md`):

```bash
pytest evals --run-llm
```

Score history (16 planted cases):

| Version | Score | What changed |
|---|---|---|
| v1: agent reads timelines and applies the rule itself | 10–11 / 16 | First breach right, severity often wrong: it confused "high" with "large number" and miscounted quarters |
| v2: prompt explains what each label means + step-by-step rule | 12–13 / 16 | `high` vs `medium` mostly fixed; still misses `early_warning` (counting positions) |
| **v3: severity calculated in dbt (`fct_quarters_to_breach`), agent reads it** | **16 / 16** (twice) | The broad question "which components breach?" also went from 1 + 10 tool calls with half the labels wrong to 1 call, all 14 right |

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'pipeline'` (or `'semantic'`) | Run from the repo root with `python -m pipeline...`, not `python pipeline/...`. |
| `ConnectionResetError` / `Connection refused` | Cube isn't running: `docker compose up -d`. If Docker itself gives a `500` error, see the Docker row in `data/README.md` → Troubleshooting. |
| `openai.AuthenticationError` | `OPENAI_API_KEY` in `.env` is missing or wrong. |
| `model ... does not exist` | `OPENAI_MODEL` names a model your key can't use. Remove the line to use the default. |
