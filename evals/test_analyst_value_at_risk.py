"""LLM eval: can the analyst agent say what capacity shortfalls cost?

The expected numbers come from the volume-at-risk marts through Cube. The marts themselves are
checked against the ground truth by dbt (dbt/tests/assert_volume_at_risk_*.sql) and by
tests/test_volume_at_risk_cube.py, so this eval only scores the agent: does it pick the right
tool and scenario and report the numbers as they are, without adding or estimating euros?

Questions:
1. Per component with a real breach (high / medium / early_warning, the RFQ trigger A
   components): revenue and units at risk without CMs, baseline.
2. The totals: the question from the business case, baseline and stretch, and the
   contribution after packaging.
3. Which hero product has the most revenue at risk.

Each answer must end with a RESULT line; numbers must be within 1%. Costs API calls, so it
only runs on request (with Docker up):
    pytest evals --run-llm
"""
import re

import pytest

from semantic.cube_client import load
from tests.ground_truth import LATEST, ground_truth

pytestmark = [pytest.mark.llm, pytest.mark.usefixtures("cube")]

NUMBER_FORMAT = "plain numbers, no currency sign or thousands separators"


def numbers(line: str) -> dict[str, float | str]:
    """'a=1 234.5; b=E12345' -> {'a': 1234.5, 'b': 'E12345'}"""
    result = {}
    for part in line.split(";"):
        if "=" not in part:
            continue
        key, value = (x.strip().strip("`*").lower() for x in part.split("=", 1))
        digits = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
        result[key] = float(digits) if re.fullmatch(r"-?\d+(\.\d+)?", digits or "x") and not re.match(r"[a-z]\d{5}", value) else value.upper()
    return result


def result_line(answer: str) -> dict:
    match = re.search(r"RESULT:\s*(.+)", answer)
    assert match, f"no RESULT line at the end of: {answer[-300:]}"
    return numbers(match.group(1))


def close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= max(0.01 * abs(expected), 1)


# --- 1. per component -------------------------------------------------------------------

def a_trigger_components() -> list[str]:
    if not LATEST:
        return []
    cases = ground_truth(LATEST, "planted_cases.csv")
    return sorted(cases[cases.severity.isin(["high", "medium", "early_warning"])].ac_code)


COMPONENTS = a_trigger_components()

COMPONENT_QUESTION = (
    "If we don't use contract manufacturers or invest, what revenue is at risk because of "
    "component {ac}, baseline forecast, over the whole forecast horizon? End your answer with "
    "exactly one line ({fmt}): RESULT: revenue_eur=<number>; units=<product units at risk>"
)


@pytest.mark.parametrize("ac", COMPONENTS)
def test_agent_reports_revenue_at_risk_of_a_component(ac):
    from pipeline.agents.analyst import ask

    expected = load({
        "measures": ["volume_at_risk.revenue_at_risk_baseline", "volume_at_risk.units_at_risk_baseline"],
        "filters": [{"member": "volume_at_risk.ac_code", "operator": "equals", "values": [ac]}],
    })[0]
    got = result_line(ask(COMPONENT_QUESTION.format(ac=ac, fmt=NUMBER_FORMAT)))
    assert close(got["revenue_eur"], float(expected["volume_at_risk.revenue_at_risk_baseline"] or 0)), got
    assert close(got["units"], float(expected["volume_at_risk.units_at_risk_baseline"])), got


# --- 2. totals ---------------------------------------------------------------------------

TOTAL_QUESTION = (
    "If we don't invest and don't use contract manufacturers, how many products can't we make "
    "and what is that worth, {scenario} forecast, whole forecast horizon? End your answer with "
    "exactly one line ({fmt}): RESULT: products=<number of products affected>; units=<product "
    "units at risk>; revenue_eur=<number>; contribution_eur=<number>; units_without_price=<number>"
)


@pytest.mark.parametrize("scenario", ["baseline", "stretch"])
def test_agent_reports_the_total_at_risk(scenario):
    from pipeline.agents.analyst import ask

    cube = "product_volume_at_risk"
    expected = load({"measures": [f"{cube}.{m}_{scenario}" for m in (
        "products_at_risk", "units_at_risk", "revenue_at_risk", "contribution_at_risk", "units_without_price")]})[0]
    got = result_line(ask(TOTAL_QUESTION.format(scenario=scenario, fmt=NUMBER_FORMAT)))
    assert got["products"] == float(expected[f"{cube}.products_at_risk_{scenario}"]), got
    for key, measure in [("units", "units_at_risk"), ("revenue_eur", "revenue_at_risk"),
                         ("contribution_eur", "contribution_at_risk"), ("units_without_price", "units_without_price")]:
        assert close(got[key], float(expected[f"{cube}.{measure}_{scenario}"])), (key, got)


# --- 3. the hero product that loses most -------------------------------------------------

HERO_QUESTION = (
    "Without CMs or investment, which hero product has the highest revenue at risk (baseline), "
    "and how much? End your answer with exactly one line ({fmt}): "
    "RESULT: pf=<PF code>; revenue_eur=<number>"
)


def test_agent_finds_the_hero_product_losing_most():
    from pipeline.agents.analyst import ask

    rows = load({"dimensions": ["product_volume_at_risk.pf_code"],
                 "measures": ["product_volume_at_risk.revenue_at_risk_baseline"],
                 "filters": [{"member": "product.is_hero", "operator": "equals", "values": ["true"]}],
                 "order": {"product_volume_at_risk.revenue_at_risk_baseline": "desc"}, "limit": 50})
    top = max((r for r in rows if r["product_volume_at_risk.revenue_at_risk_baseline"]),
              key=lambda r: float(r["product_volume_at_risk.revenue_at_risk_baseline"]))
    got = result_line(ask(HERO_QUESTION.format(fmt=NUMBER_FORMAT)))
    assert got["pf"] == top["product_volume_at_risk.pf_code"], got
    assert close(got["revenue_eur"], float(top["product_volume_at_risk.revenue_at_risk_baseline"])), got
