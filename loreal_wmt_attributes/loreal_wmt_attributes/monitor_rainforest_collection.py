"""Poll Rainforest collection every 2 min, emit on meaningful changes."""
import json
import os
import sys
import time
from pathlib import Path

import requests

ENV = Path(r"D:\brand_violations_code_refactored\.env")
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

KEY = os.environ["RAINFOREST_API_KEY"]
CACHE = Path(r"C:\Users\Admin\Downloads\loreal_product_matching attributes\loreal_upc_collection_rainforest_cache.json")
CID = json.loads(CACHE.read_text())["shards"][0]["collection_id"]

URL = f"https://api.rainforestapi.com/collections/{CID}"
last_status = None
last_bucket = -1

print(f"watching rainforest collection {CID}", flush=True)
while True:
    try:
        r = requests.get(URL, params={"api_key": KEY}, timeout=30)
        coll = r.json().get("collection", {})
        status = coll.get("status")
        count = coll.get("results_count", 0)
        total = coll.get("requests_total_count", 0) or 1
        pct = int(100 * count / total) if total else 0
        bucket = pct // 10

        emit = False
        if status != last_status:
            emit = True
        elif bucket > last_bucket:
            emit = True

        if emit:
            print(f"[{time.strftime('%H:%M:%S')}] status={status}  result_sets={count}  requests_total={total}", flush=True)
            last_status = status
            last_bucket = bucket

        if status in ("complete", "failed") or (status == "idle" and count > 0):
            print(f"TERMINAL status={status} result_sets={count} requests_total={total}", flush=True)
            sys.exit(0)
    except Exception as e:
        print(f"poll-error: {e}", flush=True)

    time.sleep(120)
