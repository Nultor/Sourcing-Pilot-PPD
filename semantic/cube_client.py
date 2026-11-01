"""Connection to the local Cube API, shared by the terminal tool (query.py) and the agents.

    from cube_client import get_meta, load            # from inside semantic/
    from semantic.cube_client import get_meta, load   # from the repo root (python -m ...)

Cube's API wants a JWT signed with CUBEJS_API_SECRET (from .env); make_token() creates one.
Standard library only, so it runs in any Python 3.
"""
import base64
import hashlib
import hmac
import json
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


def get_meta() -> dict:
    """All cubes with their measures and dimensions (names + descriptions)."""
    token = make_token(read_env()["CUBEJS_API_SECRET"])
    return call("meta", token)


def load(query: dict) -> list[dict]:
    """Run a Cube query (a dict) and return the rows as a list of dicts."""
    token = make_token(read_env()["CUBEJS_API_SECRET"])
    result = call("load?" + urllib.parse.urlencode({"query": json.dumps(query)}), token)
    return result["data"]
