"""Run a query against the local Cube API from the terminal.

    python semantic/query.py --meta                                # list cubes, measures, dimensions
    python semantic/query.py semantic/queries/top_saturated.json   # run a saved query

Cube's API wants a JWT signed with CUBEJS_API_SECRET (from .env); this script makes one.
Standard library only, so it runs in any Python 3.
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:4000/cubejs-api/v1"


def read_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def make_token(secret: str) -> str:
    def b64(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"iat": now, "exp": now + 3600}).encode())
    signature = b64(hmac.new(secret.encode(), header + b"." + payload, hashlib.sha256).digest())
    return (header + b"." + payload + b"." + signature).decode()


def call(path: str, token: str) -> dict:
    request = urllib.request.Request(f"{API}/{path}", headers={"Authorization": token})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    token = make_token(read_env()["CUBEJS_API_SECRET"])

    if sys.argv[1] == "--meta":
        for cube in call("meta", token)["cubes"]:
            print(f"\n{cube['name']}: {cube.get('description', '')}")
            members = [m for m in cube["measures"] + cube["dimensions"] if m.get("isVisible", True)]
            for member in members:
                print(f"  {member['name']:<55} {member.get('description', '')}")
        return

    query = Path(sys.argv[1]).read_text()
    result = call("load?" + urllib.parse.urlencode({"query": query}), token)
    rows = result["data"]
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0])
    print(" | ".join(c.split(".")[-1] for c in columns))
    for row in rows:
        print(" | ".join(str(row[c]) for c in columns))


if __name__ == "__main__":
    main()
