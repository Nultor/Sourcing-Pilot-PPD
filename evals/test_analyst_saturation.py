"""LLM eval: does the analyst agent label each planted saturation case correctly?

One question per planted case of the latest snapshot (the breaches and the decoys, not
the normal components). The agent's answer must end with a RESULT line, which is compared
with planted_cases.csv. Each case is its own test, so the pass count is the score.

Costs API calls, so it only runs on request (with Docker up):
    pytest evals --run-llm
"""
import re

import pandas as pd
import pytest

from tests.ground_truth import LATEST, ground_truth

pytestmark = [pytest.mark.llm, pytest.mark.usefixtures("cube")]

QUESTION = (
    "Assess capacity saturation for component {ac}. End your answer with exactly one line: "
    "RESULT: severity=<none|temporary_spike|medium|high|early_warning>; first_breach=<quarter like 2027Q1, or none>"
)
RESULT = re.compile(r"RESULT:\s*severity=(\w+);\s*first_breach=(\w+)")

CASES = (ground_truth(LATEST, "planted_cases.csv").query("case != 'normal'").to_dict("records")
         if LATEST else [])


@pytest.mark.parametrize("case", CASES, ids=[f"{c['ac_code']}-{c['case']}" for c in CASES])
def test_agent_labels_planted_case(case):
    from pipeline.agents.analyst import ask   # imported here so collecting without an API key works

    answer = ask(QUESTION.format(ac=case["ac_code"]))
    match = RESULT.search(answer)
    assert match, f"no RESULT line at the end of: {answer[-300:]}"

    expected_first = "none" if pd.isna(case["first_breach_quarter"]) else case["first_breach_quarter"]
    assert match.groups() == (case["severity"], expected_first)
