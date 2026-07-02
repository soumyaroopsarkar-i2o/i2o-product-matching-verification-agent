"""Poll BlueCart collection FEF94B9A every 2 min, emit on meaningful changes."""
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

KEY = os.environ["BLUECART_API_KEY"]
CACHE = Path(r"C:\Users\Admin\Downloads\loreal_product_matching attributes\loreal_upc_collection_cache.json")
CID = json.loads(CACHE.read_text())["shards"][0]["collection_id"]

URL = f"https://api.bluecartapi.com/collections/{CID}"
last_status = None
last_bucket = -1

print(f"watching collection {CID}", flush=True)
while True:
    try:
        r = requests.get(URL, params={"api_key": KEY}, timeout=30)
        coll = r.json().get("collection", {})
        status = coll.get("status")
        count = coll.get("results_count", 0)
        total = coll.get("requests_count", 0) or 1
        pct = int(100 * count / total)
        bucket = pct // 10  # 10% buckets

        emit = False
        if status != last_status:
            emit = True
        elif bucket > last_bucket:
            emit = True

        if emit:
            print(f"[{time.strftime('%H:%M:%S')}] status={status}  {count}/{total} ({pct}%)", flush=True)
            last_status = status
            last_bucket = bucket

        if status in ("complete", "failed") or (status == "idle" and count > 0):
            print(f"TERMINAL status={status} count={count}/{total}", flush=True)
            sys.exit(0)
    except Exception as e:
        print(f"poll-error: {e}", flush=True)

    time.sleep(120)
