"""Mirror every Nango connection's credentials into files for the sandbox.

The sandbox shell never sees NANGO_SECRET_KEY. This sidecar holds it,
and writes one JSON file per connection to a shared tmpfs:

    $OUT_DIR/<provider_config_key>/<connection_id>.json

Nango refreshes expired OAuth tokens on the detail GET, so polling
faster than the shortest token lifetime keeps the files fresh.
Stdlib only: runs on python:3.13-slim with no pip step.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def parse_connections(body: dict) -> list[tuple[str, str]]:
    return [
        (c["provider_config_key"], c["connection_id"])
        for c in body.get("connections", [])
        if c.get("provider_config_key") and c.get("connection_id")
    ]


def token_payload(detail: dict) -> dict:
    credentials = detail.get("credentials", {})
    return {
        "provider_config_key": detail.get("provider_config_key"),
        "connection_id": detail.get("connection_id"),
        "type": credentials.get("type"),
        "access_token": credentials.get("access_token") or credentials.get("apiKey"),
        "expires_at": credentials.get("expires_at"),
        "credentials": credentials,
    }


def _safe(part: str) -> str:
    # Nango ids are user-chosen; never let one escape OUT_DIR.
    return part.replace("/", "_").replace("\0", "_").lstrip(".") or "_"


def target_path(out_dir: Path, provider_config_key: str, connection_id: str) -> Path:
    return out_dir / _safe(provider_config_key) / f"{_safe(connection_id)}.json"


def _get(base_url: str, secret_key: str, path: str) -> dict:
    request = urllib.request.Request(
        f"{base_url}{path}", headers={"Authorization": f"Bearer {secret_key}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.chmod(0o444)
    tmp.replace(path)


def _detail_path(provider_config_key: str, connection_id: str) -> str:
    query = urllib.parse.urlencode({"provider_config_key": provider_config_key})
    return f"/connection/{urllib.parse.quote(connection_id, safe='')}?{query}"


def sync_once(base_url: str, secret_key: str, out_dir: Path) -> int:
    connections = parse_connections(_get(base_url, secret_key, "/connection"))
    for key, connection_id in connections:
        try:
            detail = _get(base_url, secret_key, _detail_path(key, connection_id))
            _write_atomic(target_path(out_dir, key, connection_id), token_payload(detail))
        except Exception as error:  # one bad connection must not block the rest
            print(f"skip {key}/{connection_id}: {error}", file=sys.stderr, flush=True)
    return len(connections)


def main() -> None:
    base_url = os.environ["NANGO_URL"].rstrip("/")
    secret_key = os.environ["NANGO_SECRET_KEY"]
    out_dir = Path(os.environ.get("OUT_DIR", "/run/secrets/nango"))
    interval = int(os.environ.get("INTERVAL_SECONDS", "300"))
    while True:
        try:
            print(f"synced {sync_once(base_url, secret_key, out_dir)} connections", flush=True)
        except Exception as error:
            print(f"sync failed: {error}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
