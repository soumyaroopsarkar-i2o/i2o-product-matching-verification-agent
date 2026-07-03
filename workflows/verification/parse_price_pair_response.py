from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from price_workflow_common import extract_json_array, load_json, read_text_any_encoding, safe_text, write_json


EQUIV_CODES = {"E", "EQ", "EQUIV", "EQUIVALENT"}


def normalize_decision(item: Any) -> dict[str, Any] | None:
    if isinstance(item, int):
        row_idx = item
        status_code = "EQUIV"
    elif isinstance(item, list) and len(item) == 1:
        row_idx = item[0]
        status_code = "EQUIV"
    elif isinstance(item, list) and len(item) >= 2:
        row_idx = item[0]
        status_code = safe_text(item[1]).upper()
    elif isinstance(item, dict):
        row_idx = item.get("row_idx", item.get("ri"))
        status_code = safe_text(item.get("status_code", item.get("status", "EQUIV"))).upper()
    else:
        raise ValueError(f"Invalid decision item: {item!r}")

    if not isinstance(row_idx, int):
        raise ValueError(f"Invalid row_idx in decision: {item!r}")

    if status_code not in EQUIV_CODES:
        return None

    return {
        "row_idx": row_idx,
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
        if decision is None:
            continue
        row_idx = decision["row_idx"]
        if row_idx in seen:
            raise ValueError(f"Duplicate row_idx {row_idx} in batch {batch_index:03d}")
        seen.add(row_idx)
        decisions.append(decision)

    expected_set = set(expected)
    unexpected = sorted(seen - expected_set)
    if unexpected:
        raise ValueError(f"Unexpected row_idx values in batch {batch_index:03d}: {unexpected}")

    decisions.sort(key=lambda item: item["row_idx"])
    result = {
        "batch_index": batch_index,
        "row_idx_start": batch["row_idx_start"],
        "row_idx_end": batch["row_idx_end"],
        "row_count": len(expected),
        "reclassified_count": len(decisions),
        "source_raw_response_path": str(raw_path),
        "decisions": decisions,
    }
    write_json(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Stage 2A pairwise price anomaly raw responses.")
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
        print(
            f"Parsed Stage 2A batch {batch_index:03d}: "
            f"{result['reclassified_count']} reclassified rows from {result['row_count']} reviewed rows"
        )

    if not parsed:
        print("No Stage 2A raw response files found to parse.")


if __name__ == "__main__":
    main()
