"""Flatten the BlueCart JSONL results into a per-UPC CSV joined to the Loreal sheet."""
import json
from pathlib import Path

from _paths import DATA_DIR

import pandas as pd

BASE = DATA_DIR
JSONL = BASE / "loreal_upc_results" / "loreal_upc_walmart.jsonl"
XLSX = BASE / "Loreal_Consolidated_with_ASIN.xlsx"
OUT_CSV = BASE / "loreal_walmart_match.csv"
OUT_XLSX = BASE / "loreal_walmart_match.xlsx"


def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


rows = []
with open(JSONL, encoding="utf-8") as f:
    for line in f:
        for item in json.loads(line):
            req = item.get("request") or {}
            gtin = req.get("gtin")
            res = item.get("result") or {}
            prod = res.get("product") if isinstance(res, dict) else None
            prod = prod or {}

            bb = prod.get("buybox_winner") if isinstance(prod.get("buybox_winner"), dict) else {}
            price_obj = bb.get("price") if isinstance(bb.get("price"), dict) else {}
            seller = bb.get("seller") if isinstance(bb.get("seller"), dict) else {}
            crumbs = prod.get("breadcrumbs") or []
            if isinstance(crumbs, list):
                cat_path = " > ".join(c.get("name", "") for c in crumbs if isinstance(c, dict))
            else:
                cat_path = ""
            images = prod.get("images") or []
            main_image = safe_get(prod, "main_image", "link") or (images[0].get("link") if images and isinstance(images[0], dict) else None)

            rows.append({
                "EACH UPC": gtin,
                "matched": bool(prod.get("item_id")),
                "walmart_item_id": prod.get("item_id"),
                "walmart_product_id": prod.get("product_id"),
                "walmart_brand": prod.get("brand"),
                "walmart_title": prod.get("title"),
                "walmart_model": prod.get("model"),
                "walmart_type": prod.get("type"),
                "walmart_category_path": cat_path,
                "walmart_rating": prod.get("rating"),
                "walmart_ratings_total": prod.get("ratings_total"),
                "walmart_price": price_obj.get("value") if isinstance(price_obj, dict) else None,
                "walmart_currency": price_obj.get("currency") if isinstance(price_obj, dict) else None,
                "walmart_seller": seller.get("name") if isinstance(seller, dict) else None,
                "walmart_link": prod.get("link"),
                "walmart_image": main_image,
                "walmart_description": prod.get("description"),
                "walmart_ingredients": prod.get("ingredients"),
                "walmart_variants_count": len(prod.get("variants") or []) if isinstance(prod.get("variants"), list) else 0,
            })

bc_df = pd.DataFrame(rows)
print(f"BlueCart rows: {len(bc_df):,} | matched: {bc_df['matched'].sum():,}")

# Join back to original Loreal sheet
loreal = pd.read_excel(XLSX, dtype=str)
loreal["EACH UPC"] = loreal["EACH UPC"].astype(str).str.strip()
bc_df["EACH UPC"] = bc_df["EACH UPC"].astype(str).str.strip()

merged = loreal.merge(bc_df, on="EACH UPC", how="left")
merged["matched"] = merged["matched"].fillna(False)
print(f"Merged rows: {len(merged):,}")
print(f"Matched after join: {int(merged['matched'].sum()):,}")

merged.to_csv(OUT_CSV, index=False)
print(f"CSV  -> {OUT_CSV}")

# Also write an xlsx with two sheets: full + matched-only for convenience
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
    merged.to_excel(xw, sheet_name="all", index=False)
    merged[merged["matched"]].to_excel(xw, sheet_name="matched_only", index=False)
    merged[~merged["matched"]][loreal.columns.tolist()].to_excel(xw, sheet_name="unmatched", index=False)
print(f"XLSX -> {OUT_XLSX}")

# Quick brand-agreement check (Loreal brand vs Walmart brand)
m = merged[merged["matched"]].copy()
m["loreal_brand_norm"] = m["Brand"].astype(str).str.lower().str.strip()
m["walmart_brand_norm"] = m["walmart_brand"].astype(str).str.lower().str.strip()
agree = (m["loreal_brand_norm"] == m["walmart_brand_norm"]) | m["walmart_brand_norm"].str.contains(m["loreal_brand_norm"].fillna(""), na=False, regex=False)
print(f"\nBrand agreement (rough, lowercase contains): {agree.sum():,}/{len(m):,} ({100*agree.sum()/max(len(m),1):.1f}%)")

# Top sub-brands by match rate
print("\nMatch rate by Sub Brand (top 15 by count):")
sb = merged.groupby("Sub Brand").agg(total=("EACH UPC","count"), matched=("matched","sum"))
sb["rate_%"] = (100*sb["matched"]/sb["total"]).round(1)
print(sb.sort_values("total", ascending=False).head(15).to_string())

