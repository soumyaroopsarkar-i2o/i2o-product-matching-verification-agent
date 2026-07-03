"""Keepa fallback: hit /product?code=<upc>&domain=1 for the no-ASIN UPCs.

Resume-safe: each UPC's full response is cached in keepa_fallback_cache.json.
Re-running picks up exactly where it stopped.

Token-aware: checks tokensLeft up front and throttles if a single response
shows low remaining tokens (sleeps based on refillRate).
"""
import json
import logging
import os
import time
from pathlib import Path

from _paths import DATA_DIR

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ENV_FILE = Path(r"D:\brand_violations_code_refactored\.env")
for line in ENV_FILE.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

KEY = os.environ["KEEPA_API_KEY"]
DOMAIN = 1  # amazon.com

BASE = DATA_DIR
GAP_CSV = BASE / "loreal_amazon_gaps_for_keepa.csv"
CACHE_FILE = BASE / "keepa_fallback_cache.json"
RESULTS_DIR = BASE / "loreal_upc_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSONL = RESULTS_DIR / "keepa_upc_amazon.jsonl"

# Buffer to keep above (tokens we don't want to drop below before sleeping)
MIN_TOKEN_FLOOR = 20
# When throttle triggers, sleep until tokens reach this level (gives a real buffer
# so we get many calls between throttles rather than one-call-per-throttle).
THROTTLE_TARGET = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("keepa_fallback")


def get_session():
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
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
    return {"upcs": {}}


def save_cache(c: dict):
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(c, indent=2), encoding="utf-8")
    os.replace(tmp, CACHE_FILE)


def token_status() -> dict:
    r = http.get("https://api.keepa.com/token", params={"key": KEY}, timeout=30)
    r.raise_for_status()
    return r.json()


def keepa_product_by_code(upc: str) -> dict:
    """Single-UPC product lookup. Returns full response JSON."""
    params = {
        "key": KEY,
        "domain": DOMAIN,
        "code": upc,
        "history": 0,  # Skip price history (huge payload). stats/offers/buybox: omit entirely.
    }
    r = http.get("https://api.keepa.com/product", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    # Load gap UPCs
    gaps = pd.read_csv(GAP_CSV, dtype=str)
    upcs = gaps["EACH UPC"].dropna().astype(str).str.strip().tolist()
    upcs = [u for u in upcs if u]
    log.info(f"Loaded {len(upcs):,} gap UPCs from {GAP_CSV.name}")

    # Pre-flight token check
    tok = token_status()
    tokensLeft = tok.get("tokensLeft", 0)
    refillRate = tok.get("refillRate", 0)
    log.info(f"Keepa tokens before: {tokensLeft}  refillRate={refillRate}/min")
    estimated = 6 * len(upcs)
    log.info(f"Estimated need: ~{estimated} tokens for {len(upcs)} UPCs (will throttle if low)")

    cache = load_cache()
    done = cache.setdefault("upcs", {})
    log.info(f"Already cached: {len(done):,}")

    # Open output file in append mode; we'll dedupe later if needed
    pending = [u for u in upcs if u not in done]
    log.info(f"To fetch: {len(pending):,}")

    with open(OUT_JSONL, "a", encoding="utf-8") as fout:
        for i, upc in enumerate(pending, 1):
            try:
                body = keepa_product_by_code(upc)
            except Exception as e:
                log.error(f"[{i}/{len(pending)}] UPC {upc}: {e}")
                # Cache the failure so we don't hammer it
                done[upc] = {"error": str(e)[:200]}
                if i % 25 == 0:
                    save_cache(cache)
                continue

            # Record the response
            done[upc] = {
                "tokensLeft": body.get("tokensLeft"),
                "refillIn": body.get("refillIn"),
                "refillRate": body.get("refillRate"),
                "product_count": len(body.get("products") or []),
                "asin": (body.get("products") or [{}])[0].get("asin") if body.get("products") else None,
            }
            # Also write the full response (with the UPC tagged in) to JSONL
            fout.write(json.dumps({"upc": upc, "response": body}) + "\n")
            fout.flush()

            tl = body.get("tokensLeft", 0)
            rr = body.get("refillRate", 0) or 1
            if i % 25 == 0 or tl < MIN_TOKEN_FLOOR:
                save_cache(cache)
                log.info(f"[{i}/{len(pending)}] UPC {upc}: asin={done[upc]['asin']} tokensLeft={tl}")

            # Throttle if running low — refill to THROTTLE_TARGET so we get a real buffer
            if tl < MIN_TOKEN_FLOOR:
                needed = THROTTLE_TARGET - tl
                wait = max(15, int(60 * needed / rr) + 5)
                log.info(f"  tokensLeft={tl} < {MIN_TOKEN_FLOOR}; sleeping {wait}s to refill to ~{THROTTLE_TARGET} ({rr}/min)")
                time.sleep(wait)

    save_cache(cache)
    tok_after = token_status()
    log.info(f"Keepa tokens after : {tok_after.get('tokensLeft')}  used~{tokensLeft - tok_after.get('tokensLeft', 0)}")
    log.info(f"Done. Raw responses -> {OUT_JSONL}")


if __name__ == "__main__":
    main()

