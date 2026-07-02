from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from price_workflow_common import (
    compact_json,
    get_value,
    load_rows,
    normalize_upc,
    observation_key,
    parse_price,
    safe_text,
    source_marketplace,
    target_marketplace,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "full_verification_runs"


def listing_id(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def canonical_marketplace(value: str) -> str:
    lowered = safe_text(value).lower()
    if not lowered:
        return ""
    if "amazon" in lowered:
        return "Amazon"
    if "walmart" in lowered:
        return "Walmart"
    if "target" in lowered:
        return "Target"
    if "kroger" in lowered:
        return "Kroger"
    if "shoprite" in lowered:
        return "ShopRite"
    if "meijer" in lowered:
        return "Meijer"
    if "samsclub" in lowered or "sam's club" in lowered or "sams club" in lowered:
        return "Sam's Club"
    if "costco" in lowered:
        return "Costco"
    return safe_text(value)


def source_upc(row: dict[str, Any]) -> str:
    return normalize_upc(get_value(row, "Source_UPC"))


def target_upc(row: dict[str, Any]) -> str:
    return normalize_upc(get_value(row, "Target_UPC"))


def candidate_upcs(row: dict[str, Any]) -> list[str]:
    upcs = []
    for upc in (source_upc(row), target_upc(row)):
        if upc and upc not in upcs:
            upcs.append(upc)
    return upcs


def add_observation(observations: list[dict[str, Any]], seen: set[tuple[str, str, str, str]], obs: dict[str, Any]) -> None:
    key = observation_key(obs)
    if key in seen:
        return
    seen.add(key)
    observations.append(obs)


def add_grouped_observation(grouped: dict[str, list[dict[str, Any]]], seen_by_upc: dict[str, set[tuple[str, str, str, str]]], upc: str, obs: dict[str, Any]) -> None:
    if not upc:
        return
    grouped.setdefault(upc, [])
    seen = seen_by_upc.setdefault(upc, set())
    add_observation(grouped[upc], seen, obs)


def build_observations(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen_by_upc: dict[str, set[tuple[str, str, str, str]]] = {}
    for row in rows:
        row_source_upc = source_upc(row)
        row_target_upc = target_upc(row)

        source_price = parse_price(row.get("Source_Price"))
        if source_price is not None:
            add_grouped_observation(
                grouped,
                seen_by_upc,
                row_source_upc or row_target_upc,
                {
                    "m": canonical_marketplace(source_marketplace(row)),
                    "id": listing_id(get_value(row, "Source_ASIN"), get_value(row, "Source_URL")),
                    "p": source_price,
                    "cur": get_value(row, "Source_Currency"),
                    "ri": row["row_idx"],
                },
            )

        target_price = parse_price(row.get("Target_Price"))
        if target_price is not None:
            add_grouped_observation(
                grouped,
                seen_by_upc,
                row_target_upc or row_source_upc,
                {
                    "m": canonical_marketplace(target_marketplace(row)),
                    "id": listing_id(get_value(row, "Target_Item_ID"), get_value(row, "Target_Product_ID"), get_value(row, "Target_URL")),
                    "p": target_price,
                    "cur": get_value(row, "Target_Currency"),
                    "ri": row["row_idx"],
                },
            )
    for upc, observations in grouped.items():
        observations.sort(key=lambda item: (safe_text(item.get("cur")), float(item["p"]), safe_text(item.get("m"))))
    return grouped


def combine_observations(upcs: list[str], observations_by_upc: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for upc in upcs:
        for observation in observations_by_upc.get(upc, []):
            add_observation(observations, seen, observation)
    observations.sort(key=lambda item: (safe_text(item.get("cur")), float(item["p"]), safe_text(item.get("m"))))
    return observations


def marketplace_count(observations: list[dict[str, Any]]) -> int:
    return len({safe_text(obs.get("m")).lower() for obs in observations if safe_text(obs.get("m"))})


def is_equivalent_candidate(row: dict[str, Any]) -> bool:
    return (
        get_value(row, "Match Status").lower() == "equivalent"
        or get_value(row, "reclassified_status").lower() == "equivalent"
    )


def make_candidate_record(row: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ri": row["row_idx"],
        "er": row["excel_row"],
        "candidate_source": "stage2a_reclassified" if get_value(row, "reclassified_status").lower() == "equivalent" else "stage1_equivalent",
        "upcs": candidate_upcs(row),
        "pair": {
            "s_mkt": canonical_marketplace(source_marketplace(row)),
            "s_id": listing_id(get_value(row, "Source_ASIN"), get_value(row, "Source_URL")),
            "s_price": get_value(row, "Source_Price"),
            "s_cur": get_value(row, "Source_Currency"),
            "t_mkt": canonical_marketplace(target_marketplace(row)),
            "t_id": listing_id(get_value(row, "Target_Item_ID"), get_value(row, "Target_Product_ID"), get_value(row, "Target_URL")),
            "t_price": get_value(row, "Target_Price"),
            "t_cur": get_value(row, "Target_Currency"),
        },
        "prices": observations,
    }


def make_instruction(
    *,
    input_workbook: Path,
    output_workbook: Path,
    batch_index: int,
    batch_rows: list[dict[str, Any]],
) -> str:
    expected_indices = [row["ri"] for row in batch_rows]
    payload = compact_json(batch_rows)
    return f"""# Marketplace Outlier Verification Stage 2B Batch {batch_index:03d}

You are running Stage 2B of a two-stage product verification pipeline.

Important:
- Do not run tools.
- Do not read or write files.
- Every row below is an Equivalent match, either from Stage 1 product verification or Stage 2A price-anomaly reclassification.
- The script has already grouped rows by source and target UPC and filtered to UPC groups with more than 2 marketplaces with usable price data.

Audit paths:
- Stage 2A workbook: {input_workbook}
- Stage 2B output workbook planned by merge script: {output_workbook}

## Your Stage 2B Task

For each row, use the provided UPC marketplace prices to identify which marketplace has the anomalous equivalent-match price.

Return only compact JSON. Do not include markdown, prose, code fences, or comments.

Use this schema exactly:

```json
[[row_idx,marketplace,reason],...]
```

Rules:
- Include every expected row_idx exactly once.
- Do not include any row_idx outside this batch.
- `marketplace` must be the marketplace name with the anomalous price, for example "Walmart" or "Amazon".
- If no single marketplace can be identified, use an empty string for `marketplace`.
- Use the source/target UPC-level marketplace price group to compare common price behavior.
- Prefer the marketplace price that is least consistent with the common UPC-level price range.
- Keep reason concise.

Expected row_idx values:

```json
{compact_json(expected_indices)}
```

Batch rows:

```json
{payload}
```
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Stage 2B marketplace outlier batches.")
    parser.add_argument("--input-workbook", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--run-id", help="Optional run id. Defaults to marketplace_outlier_YYYYMMDD_HHMMSS.")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    input_workbook = args.input_workbook.resolve()
    if not input_workbook.exists():
        raise FileNotFoundError(input_workbook)

    run_id = args.run_id or f"marketplace_outlier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = (args.output_root / run_id).resolve()
    instruction_dir = run_dir / "instructions"
    payload_dir = run_dir / "payloads"
    raw_dir = run_dir / "raw_responses"
    result_dir = run_dir / "results"
    final_dir = run_dir / "final"
    for directory in (instruction_dir, payload_dir, raw_dir, result_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    headers, rows = load_rows(input_workbook)
    observations_by_upc = build_observations(rows)
    candidate_rows = [row for row in rows if is_equivalent_candidate(row)]
    stage1_equivalent_rows = [
        row
        for row in candidate_rows
        if get_value(row, "Match Status").lower() == "equivalent"
    ]
    stage2a_reclassified_rows = [
        row
        for row in candidate_rows
        if get_value(row, "reclassified_status").lower() == "equivalent"
    ]

    eligible_records: list[dict[str, Any]] = []
    skipped_decisions: list[dict[str, Any]] = []
    for row in candidate_rows:
        upcs = candidate_upcs(row)
        observations = combine_observations(upcs, observations_by_upc)
        count = marketplace_count(observations)
        if count <= 2:
            skipped_decisions.append(
                {
                    "row_idx": row["row_idx"],
                    "status": "Skipped - Insufficient Marketplace Prices",
                    "reason": f"UPC group {', '.join(upcs) or 'unknown'} has {count} marketplaces with usable price data; requires >2.",
                }
            )
            continue
        eligible_records.append(make_candidate_record(row, observations))

    output_workbook = final_dir / f"{input_workbook.stem}_marketplace_outlier_output.xlsx"
    batches: list[dict[str, Any]] = []
    for batch_index, start in enumerate(range(0, len(eligible_records), args.batch_size)):
        batch_rows = eligible_records[start : start + args.batch_size]
        payload_path = payload_dir / f"batch_{batch_index:03d}.json"
        instruction_path = instruction_dir / f"instruction_{batch_index:03d}.md"
        raw_response_path = raw_dir / f"raw_{batch_index:03d}.txt"
        result_path = result_dir / f"result_{batch_index:03d}.json"

        write_json(payload_path, batch_rows)
        instruction = make_instruction(
            input_workbook=input_workbook,
            output_workbook=output_workbook,
            batch_index=batch_index,
            batch_rows=batch_rows,
        )
        instruction_path.write_text(instruction, encoding="utf-8")

        batches.append(
            {
                "batch_index": batch_index,
                "row_idx_start": batch_rows[0]["ri"],
                "row_idx_end": batch_rows[-1]["ri"],
                "row_count": len(batch_rows),
                "instruction_path": str(instruction_path),
                "payload_path": str(payload_path),
                "raw_response_path": str(raw_response_path),
                "result_path": str(result_path),
                "expected_row_idx": [row["ri"] for row in batch_rows],
            }
        )

    manifest = {
        "stage": "stage2b_marketplace_outlier",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "input_workbook": str(input_workbook),
        "output_workbook": str(output_workbook),
        "batch_size": args.batch_size,
        "total_workbook_data_rows": len(rows),
        "candidate_reclassified_rows": len(stage2a_reclassified_rows),
        "candidate_stage1_equivalent_rows": len(stage1_equivalent_rows),
        "candidate_equivalent_rows": len(candidate_rows),
        "eligible_rows": len(eligible_records),
        "skipped_decisions": skipped_decisions,
        "headers": headers,
        "batches": batches,
    }
    write_json(run_dir / "manifest.json", manifest)

    print(f"Prepared {len(batches)} Stage 2B batches in {run_dir}")
    print(f"Candidate Stage 1 Equivalent rows: {len(stage1_equivalent_rows)}")
    print(f"Candidate Stage 2A reclassified rows: {len(stage2a_reclassified_rows)}")
    print(f"Candidate Equivalent rows: {len(candidate_rows)}")
    print(f"Eligible marketplace outlier rows: {len(eligible_records)}")
    print(f"Skipped insufficient marketplace rows: {len(skipped_decisions)}")
    print(f"Manifest: {run_dir / 'manifest.json'}")
    print(f"Output workbook will be: {output_workbook}")


if __name__ == "__main__":
    main()
