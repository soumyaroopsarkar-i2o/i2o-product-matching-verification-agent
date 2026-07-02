"""Run BlueCart Collections for all Loreal UPCs (type=product, gtin=...).

Phase 1: create collection, add requests, start.
Phase 2: poll until complete, download all result pages.

Resume-safe via cache file. Re-run to continue from wherever it stopped.
"""
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Load API key from brand_violations .env ───────────────────────────────────
ENV_FILE = Path(r"D:\brand_violations_code_refactored\.env")
for line in ENV_FILE.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

BLUECART_API_KEY = os.environ["BLUECART_API_KEY"]
BLUECART_BASE_URL = "https://api.bluecartapi.com"

POLL_INTERVAL = 30
BATCH_SIZE = 1000
MAX_COLLECTION_SIZE = 4900

BASE_DIR = Path(__file__).resolve().parent
XLSX_PATH = BASE_DIR / "Loreal_Consolidated_with_ASIN.xlsx"
CACHE_FILE = BASE_DIR / "loreal_upc_collection_cache.json"
RESULTS_DIR = BASE_DIR / "loreal_upc_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSONL = RESULTS_DIR / "loreal_upc_walmart.jsonl"

COLLECTION_NAME = "Loreal_UPC_Walmart_Product"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("loreal_upc")


def get_session():
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "PUT", "POST", "OPTIONS"],
    )
    a = HTTPAdapter(max_retries=retries)
    s.mount("http://", a)
    s.mount("https://", a)
    return s


http = get_session()


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Cache corrupt; starting fresh.")
    return {}


def save_cache(c: dict):
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(c, indent=2), encoding="utf-8")
    os.replace(tmp, CACHE_FILE)


def load_upcs() -> list[str]:
    df = pd.read_excel(XLSX_PATH, dtype=str)
    upcs = df["EACH UPC"].dropna().astype(str).str.strip()
    upcs = upcs[upcs != ""].drop_duplicates().tolist()
    log.info(f"Loaded {len(upcs):,} unique UPCs from {XLSX_PATH.name}")
    return upcs


def create_collection(name: str) -> str | None:
    body = {"name": name, "schedule_type": "manual", "request_type": "product"}
    r = http.post(f"{BLUECART_BASE_URL}/collections", params={"api_key": BLUECART_API_KEY}, json=body)
    r.raise_for_status()
    cid = r.json().get("collection", {}).get("id")
    log.info(f"Created collection '{name}' -> {cid}")
    return cid


def add_requests(cid: str, reqs: list[dict]) -> bool:
    total = len(reqs)
    log.info(f"Adding {total:,} requests in batches of {BATCH_SIZE}")
    for i in range(0, total, BATCH_SIZE):
        batch = reqs[i : i + BATCH_SIZE]
        r = http.put(
            f"{BLUECART_BASE_URL}/collections/{cid}",
            params={"api_key": BLUECART_API_KEY},
            json={"requests": batch},
        )
        if r.status_code >= 400:
            log.error(f"Batch {i//BATCH_SIZE+1} failed: {r.status_code} {r.text[:300]}")
            return False
        log.info(f"  Batch {i//BATCH_SIZE+1}: {len(batch)} added")
    return True


def start_collection(cid: str) -> bool:
    r = http.get(f"{BLUECART_BASE_URL}/collections/{cid}/start", params={"api_key": BLUECART_API_KEY})
    if r.status_code >= 400:
        log.error(f"Start failed: {r.status_code} {r.text[:300]}")
        return False
    log.info(f"Started collection {cid}")
    return True


def poll_until_complete(cid: str):
    log.info(f"Polling {cid} every {POLL_INTERVAL}s")
    while True:
        try:
            r = http.get(f"{BLUECART_BASE_URL}/collections/{cid}", params={"api_key": BLUECART_API_KEY})
            r.raise_for_status()
            coll = r.json().get("collection", {})
            status = coll.get("status")
            count = coll.get("results_count", 0)
            total = coll.get("requests_count", "?")
            log.info(f"  status={status}  results={count}/{total}")
            if status in ("complete", "failed") or (status == "idle" and count > 0):
                return status
        except Exception as e:
            log.error(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)


def download_results(cid: str, out_file: Path, cache_entry: dict) -> bool:
    if not cache_entry.get("download_links"):
        r = http.get(
            f"{BLUECART_BASE_URL}/collections/{cid}/results/1",
            params={"api_key": BLUECART_API_KEY, "format": "json"},
        )
        r.raise_for_status()
        links = r.json().get("result", {}).get("download_links", {}).get("pages", [])
        if not links:
            log.warning(f"No download links. Response keys: {list(r.json().get('result', {}).keys())}")
            return False
        cache_entry["download_links"] = links
        cache_entry["downloaded_pages"] = []
        log.info(f"Got {len(links)} download link(s)")

    links = cache_entry["download_links"]
    done = set(cache_entry.get("downloaded_pages", []))

    with open(out_file, "a", encoding="utf-8") as f:
        for i, url in enumerate(links):
            if url in done:
                log.info(f"  Page {i+1}/{len(links)}: already saved")
                continue
            try:
                pr = http.get(url)
                pr.raise_for_status()
                f.write(json.dumps(pr.json()) + "\n")
                done.add(url)
                cache_entry["downloaded_pages"] = list(done)
                log.info(f"  Page {i+1}/{len(links)}: downloaded")
            except Exception as e:
                log.error(f"Page {i+1} failed: {e}")
                return False

    if len(done) == len(links) and links:
        cache_entry["downloaded"] = True
        log.info(f"All pages saved -> {out_file}")
        return True
    return False


def main():
    cache = load_cache()
    upcs = load_upcs()

    requests_payload = [{"type": "product", "gtin": u} for u in upcs]

    # one shard expected (3,758 < MAX_COLLECTION_SIZE)
    shards = [
        requests_payload[i : i + MAX_COLLECTION_SIZE]
        for i in range(0, len(requests_payload), MAX_COLLECTION_SIZE)
    ]
    log.info(f"{len(requests_payload):,} requests -> {len(shards)} shard(s)")

    shard_cache_list = cache.setdefault("shards", [])
    while len(shard_cache_list) < len(shards):
        shard_cache_list.append({})

    # ── Phase 1: create / add / start ─────────────────────────────────────────
    for idx, (shard_reqs, sc) in enumerate(zip(shards, shard_cache_list)):
        label = f"{COLLECTION_NAME}_shard{idx+1}"

        if not sc.get("collection_id"):
            cid = create_collection(label)
            if not cid:
                return
            sc["collection_id"] = cid
            sc["status"] = "created"
            save_cache(cache)
        cid = sc["collection_id"]

        if not sc.get("requests_added"):
            if not add_requests(cid, shard_reqs):
                return
            sc["requests_added"] = True
            sc["total_requests"] = len(shard_reqs)
            save_cache(cache)
        else:
            log.info(f"Shard {idx+1}: requests already added")

        if sc.get("status") not in ("started", "complete", "idle"):
            if not start_collection(cid):
                return
            sc["status"] = "started"
            save_cache(cache)
        else:
            log.info(f"Shard {idx+1}: already {sc['status']}")

    # ── Phase 2: poll + download ──────────────────────────────────────────────
    for idx, sc in enumerate(shard_cache_list):
        cid = sc["collection_id"]
        if sc.get("downloaded"):
            log.info(f"Shard {idx+1} ({cid}): already downloaded")
            continue
        if sc.get("status") not in ("complete", "idle"):
            sc["status"] = poll_until_complete(cid) or sc["status"]
            save_cache(cache)
        download_results(cid, OUT_JSONL, sc)
        save_cache(cache)

    log.info(f"Done. Results -> {OUT_JSONL}")


if __name__ == "__main__":
    main()
