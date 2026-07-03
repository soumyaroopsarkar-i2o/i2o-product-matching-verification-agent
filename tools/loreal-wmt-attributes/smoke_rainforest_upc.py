"""Smoke test: Rainforest type=product&gtin=... for 5 Loreal UPCs.

Confirms response shape and resolve rate before the bulk collection.
"""
import json
import os
import time
from pathlib import Path

from _paths import DATA_DIR

import pandas as pd
import requests

ENV = Path(r"D:\brand_violations_code_refactored\.env")
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

KEY = os.environ["RAINFOREST_API_KEY"]
URL = "https://api.rainforestapi.com/request"

XLSX = DATA_DIR / "Loreal_Consolidated_with_ASIN.xlsx"
df = pd.read_excel(XLSX, dtype=str)
sample = df[["EACH UPC", "Sub Brand", "Brand"]].dropna(subset=["EACH UPC"]).sample(5, random_state=42)

results = []
for _, row in sample.iterrows():
    upc = row["EACH UPC"].strip()
    params = {"api_key": KEY, "type": "product", "gtin": upc, "amazon_domain": "amazon.com"}
    t0 = time.time()
    try:
        r = requests.get(URL, params=params, timeout=60)
        dt = time.time() - t0
        body = r.json()
    except Exception as e:
        print(f"UPC {upc}: ERROR {e}")
        continue

    prod = body.get("product") or {}
    asin = prod.get("asin")
    title = prod.get("title")
    brand = prod.get("brand")
    cats = prod.get("categories") or []
    cat_path = " > ".join(c.get("name", "") for c in cats if isinstance(c, dict))
    bb = prod.get("buybox_winner") if isinstance(prod.get("buybox_winner"), dict) else {}
    price_obj = bb.get("price") if isinstance(bb.get("price"), dict) else {}
    price = price_obj.get("value") if isinstance(price_obj, dict) else None
    success = body.get("request_info", {}).get("success")

    print(f"UPC {upc} | loreal:{row['Sub Brand']!r} brand:{row['Brand']!r}")
    print(f"  http={r.status_code} t={dt:.1f}s  api_success={success}")
    print(f"  asin={asin}  amazon_brand={brand}")
    print(f"  amazon_title={title}")
    print(f"  category_path={cat_path}")
    print(f"  price={price}")
    print(f"  top-level keys: {list(body.keys())}")
    print()
    results.append({"upc": upc, "status": r.status_code, "asin": asin, "title": title, "brand": brand, "raw": body})

out = DATA_DIR / "smoke_rainforest_upc_results.json"
out.write_text(json.dumps(results, indent=2, default=str))
print(f"Full responses -> {out}")

