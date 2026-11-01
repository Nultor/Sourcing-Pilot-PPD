"""Run a query against the local Cube API from the terminal.

    python semantic/query.py --meta                                # list cubes, measures, dimensions
    python semantic/query.py semantic/queries/top_saturated.json   # run a saved query

The connection to Cube (token, HTTP request) lives in cube_client.py.
"""
import json
import sys
from pathlib import Path

from cube_client import get_meta, load


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)

    if sys.argv[1] == "--meta":
        for cube in get_meta()["cubes"]:
            print(f"\n{cube['name']}: {cube.get('description', '')}")
            members = [m for m in cube["measures"] + cube["dimensions"] if m.get("isVisible", True)]
            for member in members:
                print(f"  {member['name']:<55} {member.get('description', '')}")
        return

    query = json.loads(Path(sys.argv[1]).read_text())
    rows = load(query)
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0])
    print(" | ".join(c.split(".")[-1] for c in columns))
    for row in rows:
        print(" | ".join(str(row[c]) for c in columns))


if __name__ == "__main__":
    main()
