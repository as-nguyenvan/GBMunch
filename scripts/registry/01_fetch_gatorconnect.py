#!/usr/bin/env python3
"""Fetch complete public GatorConnect organization directory + details."""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

BASE = "https://gatorconnect.ufl.edu"
SEARCH = f"{BASE}/api/discovery/search/organizations"
DETAIL = f"{BASE}/api/discovery/organization/{{oid}}"
UA = "GatorGrubRegistryBot/0.1 (+UF student promptathon research; contact via project)"

# CampusLabs certs sometimes fail on stock macOS Python; prefer certifi if present.
try:
    import certifi

    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl.create_default_context()
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE


def get_json(url: str, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, context=CTX, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def fetch_directory(page_size: int = 100) -> list[dict]:
    all_rows: list[dict] = []
    skip = 0
    total = None
    while True:
        url = f"{SEARCH}?top={page_size}&skip={skip}"
        data = get_json(url)
        if total is None:
            total = data.get("@odata.count")
            print(f"Reported total: {total}", flush=True)
        batch = data.get("value") or []
        if not batch:
            break
        all_rows.extend(batch)
        skip += len(batch)
        print(f"Listed {len(all_rows)}/{total}", flush=True)
        if total is not None and len(all_rows) >= total:
            break
        if len(batch) < page_size:
            break
        time.sleep(0.15)
    return all_rows


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("Fetching directory listing...", flush=True)
    rows = fetch_directory()
    list_path = RAW / f"gatorconnect_search_{stamp}.json"
    list_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (RAW / "gatorconnect_search_latest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {list_path} ({len(rows)} orgs)", flush=True)

    details = []
    errors = []
    for i, row in enumerate(rows, 1):
        oid = row.get("Id") or row.get("id")
        try:
            detail = get_json(DETAIL.format(oid=oid))
            details.append({"search": row, "detail": detail})
        except Exception as e:
            errors.append({"id": oid, "error": str(e)})
            details.append({"search": row, "detail": None, "error": str(e)})
        if i % 25 == 0 or i == len(rows):
            print(f"Details {i}/{len(rows)} (errors={len(errors)})", flush=True)
        time.sleep(0.12)

    det_path = RAW / f"gatorconnect_details_{stamp}.json"
    det_path.write_text(json.dumps(details, indent=2), encoding="utf-8")
    (RAW / "gatorconnect_details_latest.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    (RAW / "gatorconnect_fetch_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    meta = {
        "fetched_at": stamp,
        "count_search": len(rows),
        "count_details_ok": sum(1 for d in details if d.get("detail")),
        "count_errors": len(errors),
        "base": BASE,
    }
    (RAW / "gatorconnect_fetch_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()
