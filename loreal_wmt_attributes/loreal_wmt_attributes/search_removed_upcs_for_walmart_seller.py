from __future__ import annotations

import argparse
import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
ENV_FILE = Path(r"D:\brand_violations_code_refactored\.env")
AUDIT_CSV = BASE / "removed_upcs_walmart_seller_audit.csv"
OUT_JSONL = BASE / "removed_upcs_bluecart_search_cache.jsonl"
OUT_CSV = BASE / "removed_upcs_bluecart_search_summary.csv"
API_URL = "https://api.bluecartapi.com/request"


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def norm_upc(value) -> str:
    digits = "".join(ch for ch in clean(value) if ch.isdigit())
    return digits.lstrip("0") or digits


def is_walmart_seller(value) -> bool:
    seller = clean(value).lower()
    return seller in {"walmart", "walmart.com"} or seller.startswith("walmart.com ")


def seller_name(obj) -> str:
    if isinstance(obj, dict):
        return clean(obj.get("name") or obj.get("seller") or obj.get("displayName"))
    return clean(obj)


def load_removed_upcs() -> list[str]:
    with AUDIT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    seen = set()
    out = []
    for row in rows:
        upc = clean(row.get("UPC"))
        if upc and upc not in seen:
            seen.add(upc)
            out.append(upc)
    return out


def completed_upcs() -> set[str]:
    done = set()
    if not OUT_JSONL.exists():
        return done
    with OUT_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                done.add(json.loads(line).get("upc"))
            except json.JSONDecodeError:
                continue
    return {u for u in done if u}


def request_bluecart(api_key: str, params: dict) -> dict:
    query = urlencode({"api_key": api_key, **params})
    request = Request(f"{API_URL}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    last_error = None
    for attempt in range(5):
        try:
            with urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except Exception as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(2**attempt)
    raise last_error


def iter_search_results(payload: dict):
    for key in ("search_results", "organic_results", "results"):
        results = payload.get(key)
        if isinstance(results, list):
            yield from results
            return
    search_results = payload.get("search_results")
    if isinstance(search_results, dict):
        for key in ("items", "results", "products"):
            items = search_results.get(key)
            if isinstance(items, list):
                yield from items
                return


def candidate_from_search_result(result: dict) -> dict:
    product = result.get("product") if isinstance(result.get("product"), dict) else result
    primary_offer = product.get("primary_offer") if isinstance(product.get("primary_offer"), dict) else {}
    if not primary_offer:
        primary_offer = result.get("primary_offer") if isinstance(result.get("primary_offer"), dict) else {}
    seller = seller_name(primary_offer.get("seller"))
    if not seller:
        seller = seller_name(product.get("seller") or result.get("seller"))

    item_id = clean(product.get("item_id") or product.get("us_item_id") or product.get("id"))
    link = clean(product.get("link") or product.get("product_url") or result.get("link"))
    if not item_id and link:
        parts = [p for p in urlparse(link).path.split("/") if p]
        if "ip" in parts:
            idx = parts.index("ip")
            if len(parts) > idx + 1:
                item_id = parts[-1]

    return {
        "item_id": item_id,
        "link": link,
        "title": clean(product.get("title") or product.get("name")),
        "brand": clean(product.get("brand")),
        "seller": seller,
        "price": clean(primary_offer.get("offer_price") or primary_offer.get("price") or result.get("price")),
        "raw": result,
    }


def summarize_payload(upc: str, search_payload: dict, product_payloads: list[dict]) -> dict:
    search_candidates = [candidate_from_search_result(r) for r in iter_search_results(search_payload)]
    walmart_search = [c for c in search_candidates if is_walmart_seller(c["seller"])]

    walmart_products = []
    for payload in product_payloads:
        product = payload.get("product") or {}
        buybox = product.get("buybox_winner") if isinstance(product.get("buybox_winner"), dict) else {}
        seller = seller_name(buybox.get("seller"))
        exact_upc = norm_upc(product.get("upc")) == norm_upc(upc)
        if is_walmart_seller(seller) and exact_upc:
            walmart_products.append(
                {
                    "item_id": clean(product.get("item_id")),
                    "link": clean(product.get("link")),
                    "title": clean(product.get("title")),
                    "brand": clean(product.get("brand")),
                    "seller": seller,
                    "price": clean(buybox.get("price")),
                    "product_upc": clean(product.get("upc")),
                }
            )

    chosen = walmart_products[0] if walmart_products else (walmart_search[0] if walmart_search else {})
    return {
        "UPC": upc,
        "Search_Result_Count": len(search_candidates),
        "Search_Walmart_Count": len(walmart_search),
        "Product_Walmart_Count": len(walmart_products),
        "Chosen_Item_ID": clean(chosen.get("item_id")),
        "Chosen_URL": clean(chosen.get("link")),
        "Chosen_Title": clean(chosen.get("title")),
        "Chosen_Brand": clean(chosen.get("brand")),
        "Chosen_Seller": clean(chosen.get("seller")),
        "Chosen_Price": clean(chosen.get("price")),
        "Chosen_Product_UPC": clean(chosen.get("product_upc")),
    }


def append_jsonl(record: dict) -> None:
    with OUT_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_summary() -> None:
    records = []
    if OUT_JSONL.exists():
        with OUT_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
    rows = [
        summarize_payload(
            record["upc"],
            record.get("search_payload") or {},
            record.get("product_payloads") or [],
        )
        for record in records
    ]
    if not rows:
        return
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def process_upc(api_key: str, upc: str, sleep_seconds: float) -> tuple[dict, dict]:
    search_payload = request_bluecart(
        api_key,
        {"type": "search", "search_term": upc, "sort_by": "best_match"},
    )
    candidates = [candidate_from_search_result(r) for r in iter_search_results(search_payload)]
    item_ids = []
    for candidate in candidates:
        if candidate["item_id"] and candidate["item_id"] not in item_ids:
            item_ids.append(candidate["item_id"])
        if len(item_ids) >= 5:
            break

    product_payloads = []
    for item_id in item_ids:
        product_payloads.append(
            request_bluecart(api_key, {"type": "product", "item_id": item_id})
        )
        time.sleep(sleep_seconds)

    record = {
        "upc": upc,
        "search_payload": search_payload,
        "product_payloads": product_payloads,
    }
    return record, summarize_payload(upc, search_payload, product_payloads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    load_env()
    api_key = os.environ["BLUECART_API_KEY"]
    upcs = load_removed_upcs()
    done = completed_upcs()
    pending = [upc for upc in upcs if upc not in done]
    if args.limit:
        pending = pending[: args.limit]

    processed = 0
    workers = max(1, args.workers)
    if workers == 1:
        for upc in pending:
            record, summary = process_upc(api_key, upc, args.sleep)
            append_jsonl(record)
            processed += 1
            print(
                f"{processed}/{len(pending)} upc={upc} "
                f"search={summary['Search_Result_Count']} walmart={summary['Product_Walmart_Count'] or summary['Search_Walmart_Count']} "
                f"chosen={summary['Chosen_Item_ID']} seller={summary['Chosen_Seller']}"
            )
            time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_upc = {
                executor.submit(process_upc, api_key, upc, args.sleep): upc for upc in pending
            }
            for future in as_completed(future_to_upc):
                upc = future_to_upc[future]
                try:
                    record, summary = future.result()
                    append_jsonl(record)
                    processed += 1
                    print(
                        f"{processed}/{len(pending)} upc={upc} "
                        f"search={summary['Search_Result_Count']} walmart={summary['Product_Walmart_Count'] or summary['Search_Walmart_Count']} "
                        f"chosen={summary['Chosen_Item_ID']} seller={summary['Chosen_Seller']}"
                    )
                except Exception as exc:
                    print(f"ERROR upc={upc} {exc}")

    write_summary()
    print(f"processed={processed}")
    print(f"jsonl={OUT_JSONL}")
    print(f"summary={OUT_CSV}")


if __name__ == "__main__":
    main()
