"""Shared pytest setup.

Tests on the marts need loaded synthetic data and Cube up (docker compose up -d); the
`cube` fixture skips them otherwise. LLM evals (marker llm) cost API calls and only run
with --run-llm.
"""
import pytest

from tests.ground_truth import SNAPSHOTS


def pytest_addoption(parser):
    parser.addoption("--run-llm", action="store_true", help="run the LLM evals (costs API calls)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-llm"):
        return
    skip = pytest.mark.skip(reason="LLM eval: run with --run-llm")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def cube():
    """Skips the test when there is no generated data or Cube isn't reachable."""
    from semantic.cube_client import get_meta

    if not SNAPSHOTS:
        pytest.skip("no synthetic data: run python -m data_gen.generate")
    try:
        get_meta()
    except OSError as error:
        pytest.skip(f"Cube not reachable ({error}): docker compose up -d")
