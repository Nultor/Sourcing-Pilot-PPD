"""Ground truth of the generated snapshots (data/synthetic/<snapshot>/ground_truth/)."""
from pathlib import Path

import pandas as pd

SYNTHETIC = Path(__file__).resolve().parents[1] / "data" / "synthetic"
SNAPSHOTS = sorted(p.name for p in SYNTHETIC.glob("20*Q*") if p.is_dir())
LATEST = SNAPSHOTS[-1] if SNAPSHOTS else None


def ground_truth(snapshot: str, name: str) -> pd.DataFrame:
    return pd.read_csv(SYNTHETIC / snapshot / "ground_truth" / name, dtype={"ac_code": str})
