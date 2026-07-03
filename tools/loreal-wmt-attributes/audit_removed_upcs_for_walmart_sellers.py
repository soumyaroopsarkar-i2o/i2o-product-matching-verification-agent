from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from _paths import DATA_DIR

import openpyxl


BASE = DATA_DIR
ROOT = DATA_DIR
BACKUP = ROOT / "lorealpi_product_verification_output_final.backup-before-walmart-seller-filter.xlsx"
CURRENT = ROOT / "lorealpi_product_verification_output_final.xlsx"
WALMART_JSONL = BASE / "loreal_upc_results" / "loreal_upc_walmart.jsonl"
OUT_CSV = BASE / "removed_upcs_walmart_seller_audit.csv"


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def norm_upc(value) -> str:
    digits = re.sub(r"\D", "", clean(value))
    return digits.lstrip("0") or digits


def is_walmart(value) -> bool:
    seller = clean(value).lower()
    return seller in {"walmart", "walmart.com"} or seller.startswith("walmart.com ")


def sheet_rows(path: Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Product Verification"]
    rows = ws.iter_rows(values_only=True)
    headers = list(next(rows))
    for row in rows:
        yield dict(zip(headers, row))


def removed_rows():
    current_upc_item = {
        (norm_upc(row.get("Source_UPC")), clean(row.get("Target_Item_ID")))
        for row in sheet_rows(CURRENT)
    }
    rows = []
    for row in sheet_rows(BACKUP):
        key = (norm_upc(row.get("Source_UPC")), clean(row.get("Target_Item_ID")))
        seller = clean(row.get("Target_Seller"))
        if key not in current_upc_item and not is_walmart(seller):
            rows.append(row)
    return rows


def iter_cache_items():
    with WALMART_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, list):
                yield from payload
            else:
                yield payload


def cache_by_upc():
    out = {}
    for item in iter_cache_items():
        req = item.get("request") or {}
        result = item.get("result") or {}
        product = result.get("product") if isinstance(result, dict) else {}
        product = product or {}
        upc = norm_upc(req.get("gtin") or product.get("upc"))
        if upc:
            out[upc] = item
    return out


def seller_mentions(obj, path="$"):
    mentions = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            low_key = str(key).lower()
            if "seller" in low_key:
                if isinstance(value, dict):
                    name = value.get("name") or value.get("seller") or value.get("displayName")
                    if name:
                        mentions.append((f"{path}.{key}", clean(name)))
                    else:
                        mentions.extend(seller_mentions(value, f"{path}.{key}"))
                elif isinstance(value, (str, int, float)):
                    mentions.append((f"{path}.{key}", clean(value)))
                elif isinstance(value, list):
                    mentions.extend(seller_mentions(value, f"{path}.{key}"))
            elif isinstance(value, (dict, list)):
                mentions.extend(seller_mentions(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            mentions.extend(seller_mentions(value, f"{path}[{idx}]"))
    return mentions


def product_summary(item):
    result = item.get("result") or {}
    product = result.get("product") if isinstance(result, dict) else {}
    product = product or {}
    buybox = product.get("buybox_winner") if isinstance(product.get("buybox_winner"), dict) else {}
    seller = buybox.get("seller") if isinstance(buybox.get("seller"), dict) else {}
    return product, buybox, clean(seller.get("name"))


def main():
    rows = removed_rows()
    cache = cache_by_upc()
    counts = Counter()
    report_rows = []

    for row in rows:
        upc = norm_upc(row.get("Source_UPC"))
        item = cache.get(upc)
        product, buybox, cache_buybox_seller = product_summary(item or {})
        mentions = seller_mentions(item or {})
        walmart_mentions = [f"{path}: {seller}" for path, seller in mentions if is_walmart(seller)]
        all_sellers = sorted({seller for _, seller in mentions if seller})

        if not item:
            status = "not_in_cache"
        elif is_walmart(cache_buybox_seller):
            status = "cache_buybox_walmart"
        elif walmart_mentions:
            status = "cache_nested_walmart_mention"
        else:
            status = "no_walmart_seller_in_cache"
        counts[status] += 1

        report_rows.append(
            {
                "UPC": upc,
                "Source_ASIN": clean(row.get("Source_ASIN")),
                "Source_Title": clean(row.get("Source_Title")),
                "Removed_Target_Item_ID": clean(row.get("Target_Item_ID")),
                "Removed_Target_URL": clean(row.get("Target_URL")),
                "Removed_Target_Title": clean(row.get("Target_Title")),
                "Removed_Target_Seller": clean(row.get("Target_Seller")),
                "Cache_Status": status,
                "Cache_Item_ID": clean(product.get("item_id")),
                "Cache_Product_UPC": clean(product.get("upc")),
                "Cache_Title": clean(product.get("title")),
                "Cache_Buybox_Seller": cache_buybox_seller,
                "Cache_Offers_Total": clean(buybox.get("offers_total")),
                "Cache_Walmart_Seller_Mentions": " | ".join(walmart_mentions),
                "Cache_All_Seller_Mentions": " | ".join(all_sellers),
            }
        )

    fieldnames = list(report_rows[0].keys()) if report_rows else []
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    print(f"removed_rows={len(rows)}")
    print(f"unique_removed_upcs={len({norm_upc(row.get('Source_UPC')) for row in rows})}")
    print(f"status_counts={dict(counts)}")
    print(f"report={OUT_CSV}")


if __name__ == "__main__":
    main()

