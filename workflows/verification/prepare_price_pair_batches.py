from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from price_workflow_common import (
    compact_json,
    get_value,
    load_rows,
    source_marketplace,
    status_is_exact,
    target_marketplace,
    write_json,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKILL = ROOT / "agents" / "price-anomaly-detection" / "SKILL.md"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "full_verification_runs"

LONG_LIMITS = {
    "Source_Feature_Bullets": 450,
    "Source_Description": 450,
    "Target_Description": 450,
    "Target_Ingredients": 300,
}


def add_if_present(record: dict[str, Any], key: str, value: str) -> None:
    if value:
        record[key] = value


def make_pair_record(row: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "ri": row["row_idx"],
        "er": row["excel_row"],
    }
    add_if_present(record, "s_upc", get_value(row, "Source_UPC"))
    add_if_present(record, "s_mkt", source_marketplace(row))
    add_if_present(record, "s_id", get_value(row, "Source_ASIN", "Source_Product_ID", "Source_Item_ID"))
    add_if_present(record, "s_url", get_value(row, "Source_URL"))
    add_if_present(record, "s_brand", get_value(row, "Source_Brand"))
    add_if_present(record, "s_title", get_value(row, "Source_Title", limit=300))
    add_if_present(record, "s_cat", get_value(row, "Source_Category"))
    add_if_present(record, "s_price", get_value(row, "Source_Price"))
    add_if_present(record, "s_cur", get_value(row, "Source_Currency"))
    add_if_present(record, "s_seller", get_value(row, "Source_Seller"))
    add_if_present(record, "s_bullets", get_value(row, "Source_Feature_Bullets", limit=LONG_LIMITS["Source_Feature_Bullets"]))
    add_if_present(record, "s_desc", get_value(row, "Source_Description", limit=LONG_LIMITS["Source_Description"]))

    add_if_present(record, "t_mkt", target_marketplace(row))
    add_if_present(record, "t_upc", get_value(row, "Target_UPC"))
    add_if_present(record, "t_id", get_value(row, "Target_Item_ID", "Target_Product_ID"))
    add_if_present(record, "t_url", get_value(row, "Target_URL"))
    add_if_present(record, "t_brand", get_value(row, "Target_Brand"))
    add_if_present(record, "t_title", get_value(row, "Target_Title", limit=300))
    add_if_present(record, "t_model", get_value(row, "Target_Model"))
    add_if_present(record, "t_type", get_value(row, "Target_Type"))
    add_if_present(record, "t_cat", get_value(row, "Target_Category"))
    add_if_present(record, "t_price", get_value(row, "Target_Price"))
    add_if_present(record, "t_cur", get_value(row, "Target_Currency"))
    add_if_present(record, "t_seller", get_value(row, "Target_Seller"))
    add_if_present(record, "t_desc", get_value(row, "Target_Description", limit=LONG_LIMITS["Target_Description"]))
    add_if_present(record, "t_ing", get_value(row, "Target_Ingredients", limit=LONG_LIMITS["Target_Ingredients"]))
    return record


def make_instruction(
    *,
    skill_path: Path,
    skill_text: str,
    input_workbook: Path,
    output_workbook: Path,
    batch_index: int,
    batch_rows: list[dict[str, Any]],
) -> str:
    expected_indices = [row["ri"] for row in batch_rows]
    payload = compact_json(batch_rows)
    return f"""# Price Anomaly Reclassification Batch {batch_index:03d}

You are running the price anomaly reclassification step after product verification.

Important:
- Do not run tools.
- Do not read or write files.
- Review only the pairwise row data below.
- Do not perform marketplace group/outlier analysis.
- Return only row indexes that should be reclassified to Equivalent.

Audit paths:
- Skill file: {skill_path}
- Stage 1 workbook: {input_workbook}
- Output workbook planned by merge script: {output_workbook}

## Skill Rules

Follow these pairwise price anomaly rules:

```markdown
{skill_text}
```

## Your Task

For every row:
1. Check whether both pair prices are present and comparable.
2. If comparable, check whether pair prices diverge by more than +/-30%.
3. If they diverge, recheck whether the source and target products are equivalent.

Return only compact JSON. Do not include markdown, prose, code fences, or comments.

Use this schema exactly:

```json
[row_idx,...]
```

Rules:
- Include only row_idx values that meet all three conditions: comparable pair prices, +/-30% divergence, and equivalent product after recheck.
- Return [] when no rows should be reclassified.
- Do not include any row_idx outside this batch.
- Do not return reasons, statuses, prices, or row attributes.
- The merge script will fill reclassified_status = "Equivalent" for returned row_idx values.

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
    parser = argparse.ArgumentParser(description="Prepare Stage 2A pairwise price anomaly batches.")
    parser.add_argument("--input-workbook", type=Path, required=True)
    parser.add_argument("--skill", type=Path, default=DEFAULT_SKILL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--run-id", help="Optional run id. Defaults to price_pair_YYYYMMDD_HHMMSS.")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    input_workbook = args.input_workbook.resolve()
    skill_path = args.skill.resolve()
    if not input_workbook.exists():
        raise FileNotFoundError(input_workbook)
    if not skill_path.exists():
        raise FileNotFoundError(skill_path)

    run_id = args.run_id or f"price_pair_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = (args.output_root / run_id).resolve()
    instruction_dir = run_dir / "instructions"
    payload_dir = run_dir / "payloads"
    raw_dir = run_dir / "raw_responses"
    result_dir = run_dir / "results"
    final_dir = run_dir / "final"
    for directory in (instruction_dir, payload_dir, raw_dir, result_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    headers, rows = load_rows(input_workbook)
    exact_rows = [make_pair_record(row) for row in rows if status_is_exact(row)]
    skill_text = skill_path.read_text(encoding="utf-8")
    output_workbook = final_dir / f"{input_workbook.stem}_price_pair_output.xlsx"

    batches: list[dict[str, Any]] = []
    for batch_index, start in enumerate(range(0, len(exact_rows), args.batch_size)):
        batch_rows = exact_rows[start : start + args.batch_size]
        payload_path = payload_dir / f"batch_{batch_index:03d}.json"
        instruction_path = instruction_dir / f"instruction_{batch_index:03d}.md"
        raw_response_path = raw_dir / f"raw_{batch_index:03d}.txt"
        result_path = result_dir / f"result_{batch_index:03d}.json"

        write_json(payload_path, batch_rows)
        instruction = make_instruction(
            skill_path=skill_path,
            skill_text=skill_text,
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
        "stage": "stage2a_pair_price",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "input_workbook": str(input_workbook),
        "skill_path": str(skill_path),
        "output_workbook": str(output_workbook),
        "batch_size": args.batch_size,
        "total_workbook_data_rows": len(rows),
        "selected_exact_rows": len(exact_rows),
        "headers": headers,
        "batches": batches,
    }
    write_json(run_dir / "manifest.json", manifest)

    print(f"Prepared {len(batches)} Stage 2A batches in {run_dir}")
    print(f"Selected Exact rows: {len(exact_rows)}")
    print(f"Manifest: {run_dir / 'manifest.json'}")
    print(f"Output workbook will be: {output_workbook}")


if __name__ == "__main__":
    main()
