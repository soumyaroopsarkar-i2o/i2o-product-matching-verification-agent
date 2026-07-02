"""Merge Rainforest + Keepa product data into final per-UPC Amazon enrichment.

Inputs:
  - loreal_amazon_match_pre_keepa.csv      (Rainforest-flattened, joined to Loreal)
  - loreal_upc_results/keepa_upc_amazon.jsonl  (Keepa raw responses, one line per UPC)

Output:
  - loreal_amazon_match.csv
  - loreal_amazon_match.xlsx  (sheets: all / matched_only / unmatched / keepa_filled)

For each no-ASIN row in the Rainforest output, overlays Keepa-derived fields.
Keepa often returns multiple products per UPC — we pick products[0] (highest
relevance from Keepa's side).
"""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
PRE_CSV = BASE / "loreal_amazon_match_pre_keepa.csv"
KEEPA_JSONL = BASE / "loreal_upc_results" / "keepa_upc_amazon.jsonl"
OUT_CSV = BASE / "loreal_amazon_match.csv"
OUT_XLSX = BASE / "loreal_amazon_match.xlsx"


def parse_keepa_product(p: dict) -> dict:
    """Extract our standard amazon_* columns from a Keepa product object."""
    if not isinstance(p, dict):
        return {}
    cats = p.get("categoryTree") or []
    cat_path = " > ".join(c.get("name", "") for c in cats if isinstance(c, dict))
    features = p.get("features") or []
    features_text = " | ".join(features) if isinstance(features, list) else ""
    # Keepa images come as imagesCSV (comma-separated image IDs); link is constructed
    imgs_csv = p.get("imagesCSV") or ""
    first_img = imgs_csv.split(",")[0] if imgs_csv else ""
    image_url = f"https://images-na.ssl-images-amazon.com/images/I/{first_img}" if first_img else None

    return {
        "asin": p.get("asin"),
        "parent_asin": p.get("parentAsin"),
        "amazon_brand": p.get("brand"),
        "amazon_title": p.get("title"),
        "amazon_category_path": cat_path,
        "amazon_categories_flat": cat_path,
        "amazon_description": p.get("description"),
        "amazon_feature_bullets": features_text,
        "amazon_image": image_url,
        "amazon_link": f"https://www.amazon.com/dp/{p.get('asin')}" if p.get("asin") else None,
        # Fields Keepa doesn't carry as cleanly:
        "amazon_rating": None,
        "amazon_ratings_total": None,
        "amazon_price": None,
        "amazon_currency": None,
        "amazon_seller": None,
        "amazon_sub_title": None,
        "amazon_search_alias": p.get("productGroup"),
        "amazon_variants_count": "0",
    }


# Load Rainforest-flattened
rf = pd.read_csv(PRE_CSV, dtype=str)
print(f"Pre-Keepa rows: {len(rf):,} (Rainforest-resolved: {(rf['rainforest_matched']=='True').sum():,})")

# Load Keepa results: one line per UPC, with full response
keepa_by_upc = {}
if KEEPA_JSONL.exists():
    with open(KEEPA_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            upc = str(rec.get("upc", "")).strip()
            resp = rec.get("response") or {}
            products = resp.get("products") or []
            if upc and products:
                # Take the first product (Keepa's highest-relevance ranking)
                keepa_by_upc[upc] = products[0]
print(f"Keepa resolutions available: {len(keepa_by_upc):,}")

# Source column tracks where each row's amazon_* came from
rf["source"] = rf["rainforest_matched"].apply(lambda x: "rainforest" if x == "True" else "none")

# For each row not matched by Rainforest, try Keepa overlay
overlay_columns = [
    "asin", "parent_asin", "amazon_brand", "amazon_title",
    "amazon_category_path", "amazon_categories_flat", "amazon_description",
    "amazon_feature_bullets", "amazon_image", "amazon_link",
    "amazon_rating", "amazon_ratings_total", "amazon_price", "amazon_currency",
    "amazon_seller", "amazon_sub_title", "amazon_search_alias", "amazon_variants_count",
]
# Ensure columns exist
for c in overlay_columns:
    if c not in rf.columns:
        rf[c] = None

keepa_filled_count = 0
for idx, row in rf.iterrows():
    if row["source"] == "rainforest":
        continue
    upc = str(row["EACH UPC"]).strip()
    kp = keepa_by_upc.get(upc)
    if not kp:
        continue
    extracted = parse_keepa_product(kp)
    if not extracted.get("asin"):
        continue
    for col, val in extracted.items():
        if col in rf.columns:
            rf.at[idx, col] = val
    rf.at[idx, "source"] = "keepa"
    keepa_filled_count += 1

print(f"Keepa-filled rows: {keepa_filled_count:,}")
print(f"Final 'matched' (rainforest OR keepa): {(rf['source'] != 'none').sum():,}")
print(f"Still unmatched: {(rf['source'] == 'none').sum():,}")

# A unified 'matched' flag for convenience
rf["matched"] = rf["source"].apply(lambda s: s in ("rainforest", "keepa"))

rf.to_csv(OUT_CSV, index=False)
print(f"\nCSV  -> {OUT_CSV}")

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xw:
    rf.to_excel(xw, sheet_name="all", index=False)
    rf[rf["matched"]].to_excel(xw, sheet_name="matched_only", index=False)
    rf[~rf["matched"]].to_excel(xw, sheet_name="unmatched", index=False)
    rf[rf["source"] == "keepa"].to_excel(xw, sheet_name="keepa_filled", index=False)
print(f"XLSX -> {OUT_XLSX}")

# Match rate by Sub Brand (final)
print("\nFinal match rate by Sub Brand (top 15 by count):")
sb = rf.groupby("Sub Brand").agg(total=("EACH UPC", "count"), matched=("matched", "sum"))
sb["rate_%"] = (100 * sb["matched"] / sb["total"]).round(1)
print(sb.sort_values("total", ascending=False).head(15).to_string())

# Cross-marketplace overlap if walmart match exists
wm_csv = BASE / "loreal_walmart_match.csv"
if wm_csv.exists():
    wm = pd.read_csv(wm_csv, dtype=str)
    wm["EACH UPC"] = wm["EACH UPC"].astype(str).str.strip()
    rf["EACH UPC"] = rf["EACH UPC"].astype(str).str.strip()
    wm_matched = set(wm[wm["matched"].astype(str).str.lower() == "true"]["EACH UPC"])
    amz_matched = set(rf[rf["matched"]]["EACH UPC"])
    both = wm_matched & amz_matched
    only_wm = wm_matched - amz_matched
    only_amz = amz_matched - wm_matched
    all_upcs = set(rf["EACH UPC"])
    neither = all_upcs - wm_matched - amz_matched
    print(f"\nCross-marketplace coverage (Walmart + Amazon-via-RF-or-Keepa):")
    print(f"  Matched on BOTH                : {len(both):,}")
    print(f"  Matched on Walmart only        : {len(only_wm):,}")
    print(f"  Matched on Amazon only         : {len(only_amz):,}")
    print(f"  Matched on NEITHER             : {len(neither):,}")
    print(f"  Total coverage (any source)    : {len(wm_matched | amz_matched):,} / {len(all_upcs):,} ({100*len(wm_matched|amz_matched)/len(all_upcs):.1f}%)")
