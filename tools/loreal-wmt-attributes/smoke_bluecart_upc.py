"""Smoke test: BlueCart type=product&gtin=... for Loreal UPCs.

Hits 5 sample UPCs from Loreal_Consolidated_with_ASIN.xlsx and prints
whether each resolves to a Walmart product, plus key fields.
"""
import json
import os
import sys
import time
from pathlib import Path

from _paths import DATA_DIR

import pandas as pd
import requests

# Load .env from brand_violations_code_refactored
ENV_FILE = Path(r"D:\brand_violations_code_refactored\.env")
for line in ENV_FILE.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

API_KEY = os.environ["BLUECART_API_KEY"]
BASE_URL = "https://api.bluecartapi.com/request"

XLSX = DATA_DIR / "Loreal_Consolidated_with_ASIN.xlsx"
df = pd.read_excel(XLSX, dtype=str)
sample = df[["EACH UPC", "Sub Brand", "EMD", "Brand"]].dropna(subset=["EACH UPC"]).sample(5, random_state=42)

results = []
for _, row in sample.iterrows():
    upc = row["EACH UPC"].strip()
    params = {"api_key": API_KEY, "type": "product", "gtin": upc}
    t0 = time.time()
    try:
        r = requests.get(BASE_URL, params=params, timeout=60)
        dt = time.time() - t0
        body = r.json()
    except Exception as e:
        print(f"UPC {upc}: ERROR {e}")
        continue

    prod = body.get("product") or {}
    req = body.get("request_info") or {}
    title = prod.get("title")
    item_id = prod.get("item_id") or prod.get("us_item_id")
    bb = prod.get("buybox_winner") if isinstance(prod.get("buybox_winner"), dict) else {}
    price_obj = bb.get("price") if isinstance(bb.get("price"), dict) else {}
    price = price_obj.get("value") if isinstance(price_obj, dict) else None
    brand = prod.get("brand")
    found = body.get("request_metadata", {}).get("success", req.get("success"))

    print(f"UPC {upc} | loreal:{row['Sub Brand']!r} brand:{row['Brand']!r}")
    print(f"  http={r.status_code} t={dt:.1f}s  api_success={found}")
    print(f"  walmart_item_id={item_id}  walmart_brand={brand}")
    print(f"  walmart_title={title}")
    print(f"  price={price}")
    print(f"  top-level keys: {list(body.keys())}")
    print()
    results.append({"upc": upc, "status": r.status_code, "item_id": item_id, "title": title, "brand": brand, "raw": body})

out = DATA_DIR / "smoke_bluecart_upc_results.json"
out.write_text(json.dumps(results, indent=2, default=str))
print(f"Full responses -> {out}")

