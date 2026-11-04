"""LLM eval: can the analyst agent say what a component is and which products are at risk?

Two kinds of question, both checked against the ground truth of the latest snapshot:

1. Component facts. One component per family among those whose brand, material or size was
   blank in the raw component master (so the answer only comes out right if the recovery in
   dbt, the mart, Cube and the agent all work), plus two "trap" components: generic parts
   with no brand although every product using them is of one brand.
2. Products at risk. Which (hero) products use a component with a capacity problem.

Each answer must end with a RESULT line. Costs API calls, so it only runs on request
(with Docker up):
    pytest evals --run-llm
"""
import re

import pandas as pd
import pytest

from tests.ground_truth import LATEST, SYNTHETIC, ground_truth

pytestmark = [pytest.mark.llm, pytest.mark.usefixtures("cube")]


# --- 1. component facts ----------------------------------------------------------------

FACT_QUESTION = (
    "What is component {ac}: what material, brand and size is it, and is it used by a hero "
    "product? End your answer with exactly one line: "
    "RESULT: material=<material>; brand=<brand, or none if generic>; size_ml=<number, or none>; "
    "used_by_hero=<true|false>; n_products=<number of products using it>"
)
FACT_RESULT = re.compile(
    r"RESULT:\s*material=([^;]+);\s*brand=([^;]+);\s*size_ml=([^;]+);\s*"
    r"used_by_hero=(\w+);\s*n_products=(\d+)", re.IGNORECASE)


def component_cases() -> list[dict]:
    if not LATEST:
        return []
    truth = ground_truth(LATEST, "components.csv")
    raw = pd.read_csv(SYNTHETIC / LATEST / "raw" / "component_master.csv", dtype=str)
    raw["ac_code"] = raw["AC Code"].str.strip()
    t = truth.merge(raw, on="ac_code", how="left")

    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    products = ground_truth(LATEST, "products.csv").astype({"pf_code": str})
    usage = bom.merge(products, on="pf_code").groupby("ac_code").agg(
        n_products=("pf_code", "nunique"), used_by_hero=("is_hero", "any"), n_brands=("brand", "nunique"))
    t = t.merge(usage, left_on="ac_code", right_index=True)

    recovered = t[(t.Brand.isna() & t.brand.notna()) | (t.Material.isna() & t.material.notna())
                  | (t["Size (ml)"].isna() & t.size_ml.notna())]
    one_per_family = recovered.groupby("family").head(1).assign(kind="recovered")
    traps = t[t.brand.isna() & (t.n_brands == 1)].head(2).assign(kind="generic_trap")
    return pd.concat([one_per_family, traps]).to_dict("records")


COMPONENTS = component_cases()


def norm(value) -> str:
    value = "none" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    value = value.strip().strip("`*").lower()
    return value[:-2] if value.endswith(".0") else value


@pytest.mark.parametrize("case", COMPONENTS, ids=[f"{c['ac_code']}-{c['family']}-{c['kind']}" for c in COMPONENTS])
def test_agent_knows_what_a_component_is(case):
    from pipeline.agents.analyst import ask   # imported here so collecting without an API key works

    answer = ask(FACT_QUESTION.format(ac=case["ac_code"]))
    match = FACT_RESULT.search(answer)
    assert match, f"no RESULT line at the end of: {answer[-300:]}"

    material, brand, size, hero, n = (norm(g) for g in match.groups())
    assert (material, brand, size, hero, n) == (
        norm(case["material"]), norm(case["brand"]), norm(case["size_ml"]),
        str(bool(case["used_by_hero"])).lower(), str(case["n_products"]))


# --- 2. products at risk ---------------------------------------------------------------

RISK_QUESTION = (
    "{question} End your answer with exactly one line: "
    "RESULT: products=<comma-separated PF codes, or none>"
)
RISK_RESULT = re.compile(r"RESULT:\s*products=(.+)", re.IGNORECASE)

RISK_CASES = [
    ("hero_high", "Which hero products use a component with a high severity capacity breach?",
     ["high"], True),
    ("hero_any", "Which hero products are at risk from capacity problems (high, medium or early warning)?",
     ["high", "medium", "early_warning"], True),
    ("all_high", "Which products, hero or not, use a component with a high severity capacity breach?",
     ["high"], False),
]


def products_hit(severities: list[str], hero_only: bool) -> set[str]:
    cases = ground_truth(LATEST, "planted_cases.csv")
    bom = ground_truth(LATEST, "bom.csv").astype({"pf_code": str})
    products = ground_truth(LATEST, "products.csv").astype({"pf_code": str})
    hit = bom.merge(products, on="pf_code").merge(cases[["ac_code", "severity"]], on="ac_code")
    hit = hit[hit.severity.isin(severities) & (hit.is_hero | (not hero_only))]
    return set(hit.pf_code)


@pytest.mark.parametrize("name,question,severities,hero_only", RISK_CASES, ids=[c[0] for c in RISK_CASES])
def test_agent_finds_the_products_at_risk(name, question, severities, hero_only):
    from pipeline.agents.analyst import ask

    answer = ask(RISK_QUESTION.format(question=question))
    match = RISK_RESULT.search(answer)
    assert match, f"no RESULT line at the end of: {answer[-300:]}"

    listed = set(re.findall(r"[A-Z]\d{5}", match.group(1).upper()))
    assert listed == products_hit(severities, hero_only)
