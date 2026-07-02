from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from price_workflow_common import extract_json_array, load_json, read_text_any_encoding, safe_text, write_json


def normalize_decision(item: Any) -> dict[str, Any]:
    if isinstance(item, list) and len(item) == 3:
        row_idx, marketplace, reason = item
        listing_id = ""
        price = ""
        common_range = ""
    elif isinstance(item, list) and len(item) == 7:
        row_idx, status_code, marketplace, listing_id, price, common_range, reason = item
    elif isinstance(item, dict):
        row_idx = item.get("row_idx", item.get("ri"))
        marketplace = item.get("marketplace", "")
        listing_id = item.get("listing_id", "")
        price = item.get("price", "")
        common_range = item.get("common_price_range", item.get("common_range", ""))
        reason = item.get("reason", "")
    else:
        raise ValueError(f"Invalid decision item: {item!r}")

    if not isinstance(row_idx, int):
        raise ValueError(f"Invalid row_idx in decision: {item!r}")

    marketplace = safe_text(marketplace, limit=120)
    reason = safe_text(reason, limit=500)
    if not reason:
        reason = (
            "Marketplace selected from the UPC-level price distribution."
            if marketplace
            else "No clear marketplace anomaly identified from the UPC-level price distribution."
        )

    return {
        "row_idx": row_idx,
        "marketplace": marketplace,
        "listing_id": safe_text(listing_id, limit=220),
        "price": safe_text(price, limit=80),
        "common_price_range": safe_text(common_range, limit=120),
        "reason": reason,
    }


def parse_batch(run_dir: Path, batch_index: int) -> dict[str, Any]:
    manifest = load_json(run_dir / "manifest.json")
    batch = manifest["batches"][batch_index]
    raw_path = Path(batch["raw_response_path"])
    result_path = Path(batch["result_path"])
    expected = list(batch["expected_row_idx"])

    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    raw_text = read_text_any_encoding(raw_path)
    parsed = extract_json_array(raw_text)
    if not isinstance(parsed, list):
        raise ValueError("Claude response JSON must be an array")

    decisions = []
    seen: set[int] = set()
    for item in parsed:
        decision = normalize_decision(item)
        row_idx = decision["row_idx"]
        if row_idx in seen:
            raise ValueError(f"Duplicate row_idx {row_idx} in batch {batch_index:03d}")
        seen.add(row_idx)
        decisions.append(decision)

    expected_set = set(expected)
    unexpected = sorted(seen - expected_set)
    missing = sorted(expected_set - seen)
    if unexpected:
        raise ValueError(f"Unexpected row_idx values in batch {batch_index:03d}: {unexpected}")
    if missing:
        raise ValueError(f"Missing row_idx values in batch {batch_index:03d}: {missing}")

    decisions.sort(key=lambda item: item["row_idx"])
    result = {
        "batch_index": batch_index,
        "row_idx_start": batch["row_idx_start"],
        "row_idx_end": batch["row_idx_end"],
        "row_count": len(decisions),
        "source_raw_response_path": str(raw_path),
        "decisions": decisions,
    }
    write_json(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Stage 2B marketplace outlier raw responses.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--batch", type=int, help="Parse one batch index. Defaults to all available raw responses.")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    manifest = load_json(run_dir / "manifest.json")
    if args.batch is None:
        batch_indices = [
            batch["batch_index"]
            for batch in manifest["batches"]
            if Path(batch["raw_response_path"]).exists()
        ]
    else:
        batch_indices = [args.batch]

    parsed = []
    for batch_index in batch_indices:
        result = parse_batch(run_dir, batch_index)
        parsed.append(result["batch_index"])
        print(f"Parsed Stage 2B batch {batch_index:03d}: {result['row_count']} rows")

    if not parsed:
        print("No Stage 2B raw response files found to parse.")


if __name__ == "__main__":
    main()
