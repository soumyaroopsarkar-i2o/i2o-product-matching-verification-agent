from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path

from _paths import DATA_DIR
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


BASE_DIR = DATA_DIR
ENV_FILE = Path(r"D:\brand_violations_code_refactored\.env")

BLUECART_BASE_URL = "https://api.bluecartapi.com"
INPUT_PATH = BASE_DIR / "loreal_upcs_corrected.xlsx"
CACHE_FILE = BASE_DIR / "loreal_upcs_corrected_bluecart_collection_cache.json"
RESULTS_DIR = BASE_DIR / "loreal_upc_results"
OUT_JSONL = RESULTS_DIR / "loreal_upcs_corrected_walmart.jsonl"
OUT_ALL_CSV = BASE_DIR / "loreal_upcs_corrected_walmart_all_results.csv"
OUT_CSV = BASE_DIR / "loreal_upcs_corrected_walmart_1p_matches.csv"
OUT_XLSX = BASE_DIR / "loreal_upcs_corrected_walmart_1p_matches.xlsx"

COLLECTION_NAME = "loreal_upcs_corrected_Walmart_Product"
POLL_INTERVAL_SECONDS = 30
BATCH_SIZE = 1000
MAX_COLLECTION_SIZE = 4900

WALMART_SELLERS = {"walmart", "walmart.com"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("corrected_upc_walmart_1p")


def configure_paths(input_path: Path) -> None:
    global INPUT_PATH, CACHE_FILE, OUT_JSONL, OUT_ALL_CSV, OUT_CSV, OUT_XLSX, COLLECTION_NAME

    INPUT_PATH = input_path
    stem = input_path.stem
    safe_stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "upcs"
    CACHE_FILE = BASE_DIR / f"{safe_stem}_bluecart_collection_cache.json"
    OUT_JSONL = RESULTS_DIR / f"{safe_stem}_walmart.jsonl"
    OUT_ALL_CSV = BASE_DIR / f"{safe_stem}_walmart_all_results.csv"
    OUT_CSV = BASE_DIR / f"{safe_stem}_walmart_1p_matches.csv"
    OUT_XLSX = BASE_DIR / f"{safe_stem}_walmart_1p_matches.xlsx"
    COLLECTION_NAME = f"{safe_stem}_Walmart_Product"


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def normalize_upc(value) -> str:
    digits = re.sub(r"\D", "", clean(value))
    return digits


def normalize_seller(value) -> str:
    return re.sub(r"\s+", " ", clean(value)).lower()


def is_walmart_seller(value) -> bool:
    seller = normalize_seller(value)
    return seller in WALMART_SELLERS or seller.startswith("walmart.com ")


def scalar(value):
    if isinstance(value, dict):
        if "value" in value:
            return value.get("value")
        if "raw" in value:
            return value.get("raw")
    return value


def request_json(method: str, url: str, *, params: dict | None = None, body: dict | None = None, timeout: int = 180) -> dict | list:
    full_url = url
    if params:
        full_url = f"{url}?{urlencode(params)}"
    data = None
    headers = {"User-Agent": "Mozilla/5.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error = None
    for attempt in range(5):
        request = Request(full_url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"Request failed for {method} {url}: {last_error}") from last_error


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Collection cache was corrupt; starting with a fresh cache.")
    return {}


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, CACHE_FILE)


def load_upc_frame() -> pd.DataFrame:
    if INPUT_PATH.suffix.lower() == ".csv":
        df = pd.read_csv(INPUT_PATH, dtype=str)
    else:
        df = pd.read_excel(INPUT_PATH, dtype=str)

    upc_col = next((col for col in df.columns if clean(col).lower() == "upc"), df.columns[0])
    df = df.rename(columns={upc_col: "UPC"}).copy()
    df["UPC"] = df["UPC"].map(normalize_upc)
    df = df[df["UPC"] != ""].copy()
    for col in ("original_valid", "corrected_valid", "changed", "status", "note"):
        if col not in df.columns:
            df[col] = False if col in {"original_valid", "corrected_valid", "changed"} else ""
    return df


def unique_upcs(df: pd.DataFrame) -> list[str]:
    seen = set()
    out = []
    for upc in df["UPC"]:
        if upc not in seen:
            seen.add(upc)
            out.append(upc)
    return out


def create_collection(api_key: str, name: str) -> str:
    body = {"name": name, "schedule_type": "manual", "request_type": "product"}
    response = request_json("POST", f"{BLUECART_BASE_URL}/collections", params={"api_key": api_key}, body=body)
    collection_id = response.get("collection", {}).get("id")
    if not collection_id:
        raise RuntimeError(f"BlueCart did not return a collection id: {str(response)[:500]}")
    log.info("Created collection %s -> %s", name, collection_id)
    return collection_id


def add_requests(api_key: str, collection_id: str, requests_payload: list[dict]) -> None:
    log.info("Adding %s requests in batches of %s", f"{len(requests_payload):,}", f"{BATCH_SIZE:,}")
    for start in range(0, len(requests_payload), BATCH_SIZE):
        batch = requests_payload[start : start + BATCH_SIZE]
        request_json(
            "PUT",
            f"{BLUECART_BASE_URL}/collections/{collection_id}",
            params={"api_key": api_key},
            body={"requests": batch},
        )
        log.info("  Added batch %d (%d requests)", start // BATCH_SIZE + 1, len(batch))


def start_collection(api_key: str, collection_id: str) -> None:
    request_json("GET", f"{BLUECART_BASE_URL}/collections/{collection_id}/start", params={"api_key": api_key})
    log.info("Started collection %s", collection_id)


def poll_until_done(api_key: str, collection_id: str) -> str:
    while True:
        response = request_json("GET", f"{BLUECART_BASE_URL}/collections/{collection_id}", params={"api_key": api_key})
        collection = response.get("collection", {})
        status = collection.get("status")
        results_count = collection.get("results_count", 0)
        requests_count = collection.get("requests_count", "?")
        log.info("  status=%s results=%s/%s", status, results_count, requests_count)
        if status in {"complete", "failed"} or (status == "idle" and results_count):
            return status
        time.sleep(POLL_INTERVAL_SECONDS)


def download_results(api_key: str, collection_id: str, shard_cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not shard_cache.get("download_links"):
        response = request_json(
            "GET",
            f"{BLUECART_BASE_URL}/collections/{collection_id}/results/1",
            params={"api_key": api_key, "format": "json"},
        )
        links = response.get("result", {}).get("download_links", {}).get("pages", [])
        if not links:
            raise RuntimeError("BlueCart returned no result download links.")
        shard_cache["download_links"] = links
        shard_cache["downloaded_pages"] = []
        if OUT_JSONL.exists():
            OUT_JSONL.unlink()
        log.info("Got %d result page link(s)", len(links))

    done = set(shard_cache.get("downloaded_pages", []))
    with OUT_JSONL.open("a", encoding="utf-8") as f:
        for idx, url in enumerate(shard_cache["download_links"], start=1):
            if url in done:
                log.info("  Page %d already downloaded", idx)
                continue
            response = request_json("GET", url, timeout=180)
            f.write(json.dumps(response, ensure_ascii=False) + "\n")
            done.add(url)
            shard_cache["downloaded_pages"] = sorted(done)
            log.info("  Downloaded page %d/%d", idx, len(shard_cache["download_links"]))

    if len(done) == len(shard_cache["download_links"]):
        shard_cache["downloaded"] = True


def iter_items():
    if not OUT_JSONL.exists():
        return
    with OUT_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, list):
                yield from payload
            else:
                yield payload


def category_path(product: dict) -> str:
    crumbs = product.get("breadcrumbs") or product.get("categories") or []
    if not isinstance(crumbs, list):
        return ""
    return " > ".join(clean(c.get("name")) for c in crumbs if isinstance(c, dict) and clean(c.get("name")))


def image_link(product: dict) -> str:
    main = product.get("main_image")
    if isinstance(main, dict):
        return clean(main.get("link"))
    if isinstance(main, str):
        return clean(main)
    images = product.get("images") or []
    if images and isinstance(images[0], dict):
        return clean(images[0].get("link"))
    if images and isinstance(images[0], str):
        return clean(images[0])
    return ""


def extract_product_row(item: dict) -> dict:
    request = item.get("request") or {}
    result = item.get("result") or {}
    product = result.get("product") if isinstance(result, dict) else {}
    product = product or {}
    buybox = product.get("buybox_winner") if isinstance(product.get("buybox_winner"), dict) else {}
    seller = buybox.get("seller") if isinstance(buybox.get("seller"), dict) else {}
    availability = buybox.get("availability") if isinstance(buybox.get("availability"), dict) else {}
    price = scalar(buybox.get("price"))

    return {
        "UPC": normalize_upc(request.get("gtin") or product.get("upc")),
        "BlueCart_Success": bool(item.get("success")),
        "Walmart_Product_UPC": clean(product.get("upc")),
        "Walmart_Item_ID": clean(product.get("item_id") or product.get("us_item_id")),
        "Walmart_Product_ID": clean(product.get("product_id")),
        "Walmart_URL": clean(product.get("link")),
        "Walmart_Brand": clean(product.get("brand")),
        "Walmart_Title": clean(product.get("title")),
        "Walmart_Model": clean(product.get("model")),
        "Walmart_Type": clean(product.get("type")),
        "Walmart_Category_Path": category_path(product),
        "Walmart_Rating": product.get("rating"),
        "Walmart_Ratings_Total": product.get("ratings_total"),
        "Walmart_Price": price,
        "Walmart_Currency": clean(buybox.get("currency") or buybox.get("currency_symbol")),
        "Walmart_Seller": clean(seller.get("name")),
        "Walmart_Offers_Total": buybox.get("offers_total"),
        "Walmart_In_Stock": availability.get("in_stock"),
        "Walmart_Image_URL": image_link(product),
        "Walmart_Description": clean(product.get("description")),
        "Walmart_Ingredients": clean(product.get("ingredients")),
        "Is_1P_Sold_By_Walmart": is_walmart_seller(seller.get("name")),
    }


def flatten_outputs(source_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    product_rows = [extract_product_row(item) for item in iter_items()]
    results_df = pd.DataFrame(product_rows)
    if results_df.empty:
        results_df = pd.DataFrame(columns=["UPC", "Is_1P_Sold_By_Walmart"])

    counts = source_df["UPC"].value_counts().rename_axis("UPC").reset_index(name="Input_Row_Count")
    source_flags = (
        source_df.groupby("UPC", as_index=False)
        .agg(
            Any_Original_Valid=("original_valid", "max"),
            Any_Corrected_Valid=("corrected_valid", "max"),
            Any_Changed=("changed", "max"),
            Statuses=("status", lambda s: " | ".join(sorted({clean(v) for v in s if clean(v)}))),
            Notes=("note", lambda s: " | ".join(sorted({clean(v) for v in s if clean(v)}))),
        )
        .merge(counts, on="UPC", how="left")
    )

    merged = source_flags.merge(results_df, on="UPC", how="left")
    merged["BlueCart_Matched"] = merged["Walmart_Item_ID"].fillna("").astype(str).str.strip() != ""
    merged["Is_1P_Sold_By_Walmart"] = merged["Is_1P_Sold_By_Walmart"].fillna(False).astype(bool)
    walmart_1p = merged[merged["Is_1P_Sold_By_Walmart"]].copy()

    merged.to_csv(OUT_ALL_CSV, index=False, encoding="utf-8-sig")
    walmart_1p.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    summary_rows = [
        {"Metric": "Input rows", "Value": len(source_df)},
        {"Metric": "Unique UPCs submitted", "Value": source_df["UPC"].nunique()},
        {"Metric": "BlueCart product matches", "Value": int(merged["BlueCart_Matched"].sum())},
        {"Metric": "1P sold by Walmart matches", "Value": len(walmart_1p)},
        {"Metric": "Non-Walmart seller matches", "Value": int((merged["BlueCart_Matched"] & ~merged["Is_1P_Sold_By_Walmart"]).sum())},
        {"Metric": "Unmatched UPCs", "Value": int((~merged["BlueCart_Matched"]).sum())},
    ]
    seller_counts = Counter(clean(v) or "(blank)" for v in merged.loc[merged["BlueCart_Matched"], "Walmart_Seller"])
    seller_df = pd.DataFrame(
        [{"Seller": seller, "Matched_UPCs": count} for seller, count in seller_counts.most_common()]
    )

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="summary", index=False)
        walmart_1p.to_excel(writer, sheet_name="walmart_1p_matches", index=False)
        merged.to_excel(writer, sheet_name="all_upc_results", index=False)
        seller_df.to_excel(writer, sheet_name="seller_counts", index=False)

        workbook = writer.book
        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for col in sheet.columns:
                max_len = max(len(clean(cell.value)) for cell in col)
                width = min(max(max_len + 2, 10), 60)
                sheet.column_dimensions[col[0].column_letter].width = width

    return merged, walmart_1p


def run_collection(input_path: Path, force_new: bool = False) -> None:
    configure_paths(input_path)
    load_env()
    api_key = os.environ["BLUECART_API_KEY"]
    source_df = load_upc_frame()
    upcs = unique_upcs(source_df)
    log.info("Loaded %s rows and %s unique UPCs from %s", f"{len(source_df):,}", f"{len(upcs):,}", INPUT_PATH.name)

    requests_payload = [{"type": "product", "gtin": upc} for upc in upcs]
    shards = [
        requests_payload[start : start + MAX_COLLECTION_SIZE]
        for start in range(0, len(requests_payload), MAX_COLLECTION_SIZE)
    ]
    cache = {} if force_new else load_cache()
    shard_cache_list = cache.setdefault("shards", [])
    while len(shard_cache_list) < len(shards):
        shard_cache_list.append({})

    for idx, (requests_shard, shard_cache) in enumerate(zip(shards, shard_cache_list), start=1):
        label = f"{COLLECTION_NAME}_shard{idx}"
        if not shard_cache.get("collection_id"):
            shard_cache["collection_id"] = create_collection(api_key, label)
            shard_cache["status"] = "created"
            save_cache(cache)

        collection_id = shard_cache["collection_id"]
        if not shard_cache.get("requests_added"):
            add_requests(api_key, collection_id, requests_shard)
            shard_cache["requests_added"] = True
            shard_cache["total_requests"] = len(requests_shard)
            save_cache(cache)

        if shard_cache.get("status") not in {"started", "complete", "idle"}:
            start_collection(api_key, collection_id)
            shard_cache["status"] = "started"
            save_cache(cache)

    for shard_cache in shard_cache_list:
        collection_id = shard_cache["collection_id"]
        if not shard_cache.get("downloaded"):
            if shard_cache.get("status") not in {"complete", "idle"}:
                shard_cache["status"] = poll_until_done(api_key, collection_id)
                save_cache(cache)
            download_results(api_key, collection_id, shard_cache)
            save_cache(cache)

    merged, walmart_1p = flatten_outputs(source_df)
    log.info("All result rows: %s", f"{len(merged):,}")
    log.info("1P sold by Walmart matches: %s", f"{len(walmart_1p):,}")
    log.info("CSV: %s", OUT_CSV)
    log.info("XLSX: %s", OUT_XLSX)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BASE_DIR / "loreal_upcs_corrected.xlsx"), help="CSV/XLSX file containing a UPC column.")
    parser.add_argument("--force-new", action="store_true", help="Ignore the saved collection cache and create a new collection.")
    args = parser.parse_args()
    run_collection(Path(args.input), force_new=args.force_new)


if __name__ == "__main__":
    main()

