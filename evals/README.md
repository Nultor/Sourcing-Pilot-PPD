# Evals (scoring the agents)

Evals measure how well an **agent (LLM)** does its job, compared with the ground truth. They are pytest tests, but they **cost API calls** and the result can change from run to run (LLMs aren't deterministic), so they only run when you ask for them.

The free, deterministic tests are in `tests/` (see `tests/README.md`).

## Run them

Docker up, data loaded, dbt built, `OPENAI_API_KEY` in `.env`. From the repo root:

```bash
pytest evals --run-llm                 # all evals (~40 s, 16 agent runs)
pytest evals --run-llm -rf             # + a short line per failed case at the end
pytest evals --run-llm -k 366413968    # one component only
```

Without `--run-llm`, every eval is **skipped** (`s`), so nothing is spent by accident.

## `test_analyst_saturation.py`

For each planted case of the latest snapshot except the normal ones (16 cases: real breaches **and** decoys such as monthly capacity entries or unqualified CMs), the analyst agent is asked:

> Assess capacity saturation for component {ac}. End your answer with exactly one line:
> `RESULT: severity=<...>; first_breach=<quarter or none>`

The `RESULT` line is compared with `severity` and `first_breach_quarter` in `planted_cases.csv`. Each case is its own test, so **the number that pass is the score**.

**Reading a failure:**
```
assert ('high', '2027Q1') == ('medium', '2027Q1')
         └ agent's answer     └ ground truth
```

**Score history:** 10–11/16 when the agent applied the severity rule itself → 12–13/16 with a clearer prompt → **16/16** once severity was calculated in dbt (`fct_quarters_to_breach`) and the agent only reads it. See `pipeline/README.md` for details.

## Using the score

- Run it **before and after** every change to the agent (prompt, model, tools) and compare the pass counts. Run it 2–3 times if the difference is small.
- To compare models: set `OPENAI_MODEL` in `.env`, run, compare.
- When a new mart or tool should fix a kind of mistake, the score should show it. Example: `fct_quarters_to_breach` took the severity cases from 12–13 to 16/16.

## Adding an eval

New file `evals/test_<agent>_<topic>.py`:
1. Start with `pytestmark = [pytest.mark.llm, pytest.mark.usefixtures("cube")]`.
2. Build the cases from the ground truth (`tests/ground_truth.py`), one `parametrize` entry per case.
3. Ask for a fixed, machine-readable last line in the answer, and compare that, not the free text.
