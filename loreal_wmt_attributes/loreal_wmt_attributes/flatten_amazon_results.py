"""Flatten Rainforest JSONL into per-UPC CSV joined to Loreal sheet.

Emits pre-Keepa intermediate. Reports gap stats and pauses (per plan).
"""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
JSONL = BASE / "loreal_upc_results" / "loreal_upc_amazon.jsonl"
XLSX = BASE / "Loreal_Consolidated_with_ASIN.xlsx"
OUT_CSV = BASE / "loreal_amazon_match_pre_keepa.csv"
OUT_XLSX = BASE / "loreal_amazon_match_pre_keepa.xlsx"
GAP_CSV = BASE / "loreal_amazon_gaps_for_keepa.csv"


def safe_get(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


rows = []
with open(JSONL, encoding="utf-8") as f:
    for line in f:
        for item in json.loads(line):
            req = item.get("request") or {}
            gtin = req.get("gtin")
            res = item.get("result") or {}
            prod = res.get("product") if isinstance(res, dict) else None
            miss_msg = res.get("message") if isinstance(res, dict) else None

            if not prod:
                rows.append({
                    "EACH UPC": gtin,
                    "rainforest_matched": False,
                    "rainforest_miss_reason": miss_msg,
                })
                continue

            cats = prod.get("categories") or []
            cat_path = " > ".join(c.get("name", "") for c in cats if isinstance(c, dict))
            bb = prod.get("buybox_winner") if isinstance(prod.get("buybox_winner"), dict) else {}
            price_obj = bb.get("price") if isinstance(bb.get("price"), dict) else {}
            seller = bb.get("seller") if isinstance(bb.get("seller"), dict) else {}
            main_image = safe_get(prod, "main_image", "link")
            features = prod.get("feature_bullets") or []
            features_text = " | ".join(features) if isinstance(features, list) else ""
            variants = prod.get("variants")
            variants_n = len(variants) if isinstance(variants, list) else 0

            rows.append({
                "EACH UPC": gtin,
                "rainforest_matched": True,
                "rainforest_miss_reason": None,
                "asin": prod.get("asin"),
                "parent_asin": prod.get("parent_asin"),
                "amazon_brand": prod.get("brand"),
                "amazon_title": prod.get("title"),
                "amazon_category_path": cat_path,
                "amazon_categories_flat": prod.get("categories_flat"),
                "amazon_rating": prod.get("rating"),
                "amazon_ratings_total": prod.get("ratings_total"),
                "amazon_price": price_obj.get("value") if isinstance(price_obj, dict) else None,
                "amazon_currency": price_obj.get("currency") if isinstance(price_obj, dict) else None,
                "amazon_seller": seller.get("name") if isinstance(seller, dict) else None,
                "amazon_link": prod.get("link"),
                "amazon_image": main_image,
                "amazon_description": prod.get("description"),
                "amazon_feature_bullets": features_text,
                "amazon_sub_title": prod.get("sub_title", {}).get("text") if isinstance(prod.get("sub_title"), dict) else None,
                "amazon_search_alias": prod.get("search_alias"),
                "amazon_variants_count": variants_n,
            })

rf_df = pd.DataFrame(rows)
print(f"Rainforest rows: {len(rf_df):,}")
print(f"  resolved (have ASIN): {rf_df['rainforest_matched'].sum():,}")
print(f"  no-ASIN              : {(~rf_df['rainforest_matched']).sum():,}")

# Join to Loreal sheet
loreal = pd.read_excel(XLSX, dtype=str)
loreal["EACH UPC"] = loreal["EACH UPC"].astype(str).str.strip()
rf_df["EACH UPC"] = rf_df["EACH UPC"].astype(str).str.strip()
merged = loreal.merge(rf_df, on="EACH UPC", how="left")
merged["rainforest_matched"] = merged["rainforest_matched"].fillna(False)

merged.to_csv(OUT_CSV, index=False)
print(f"\nCSV  -> {OUT_CSV}")

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
    merged.to_excel(xw, sheet_name="all", index=False)
    merged[merged["rainforest_matched"]].to_excel(xw, sheet_name="matched_only", index=False)
    merged[~merged["rainforest_matched"]][list(loreal.columns) + ["rainforest_miss_reason"]].to_excel(xw, sheet_name="no_asin", index=False)
print(f"XLSX -> {OUT_XLSX}")

# Gap file — UPCs for Keepa
gaps = merged[~merged["rainforest_matched"]][["EACH UPC", "Brand", "Sub Brand", "EMD", "rainforest_miss_reason"]]
gaps.to_csv(GAP_CSV, index=False)
print(f"GAPS -> {GAP_CSV} ({len(gaps):,} UPCs)")

# Match-rate by Sub Brand
print("\nMatch rate by Sub Brand (top 15 by count):")
sb = merged.groupby("Sub Brand").agg(total=("EACH UPC","count"), matched=("rainforest_matched","sum"))
sb["rate_%"] = (100*sb["matched"]/sb["total"]).round(1)
print(sb.sort_values("total", ascending=False).head(15).to_string())

# BlueCart vs Rainforest overlap on the same UPCs (if walmart match file exists)
wm_csv = BASE / "loreal_walmart_match.csv"
if wm_csv.exists():
    wm = pd.read_csv(wm_csv, dtype=str)
    wm["EACH UPC"] = wm["EACH UPC"].astype(str).str.strip()
    wm_matched = set(wm[wm["matched"].astype(str).str.lower() == "true"]["EACH UPC"])
    rf_matched = set(merged[merged["rainforest_matched"]]["EACH UPC"])
    both = wm_matched & rf_matched
    only_wm = wm_matched - rf_matched
    only_rf = rf_matched - wm_matched
    neither = set(merged["EACH UPC"]) - wm_matched - rf_matched
    print(f"\nCross-marketplace overlap:")
    print(f"  Matched on BOTH Walmart & Amazon : {len(both):,}")
    print(f"  Matched on Walmart only          : {len(only_wm):,}")
    print(f"  Matched on Amazon only           : {len(only_rf):,}")
    print(f"  Matched on NEITHER (true gaps)   : {len(neither):,}")
