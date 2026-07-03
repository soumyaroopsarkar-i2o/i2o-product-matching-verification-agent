from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_WORKBOOK = (
    ROOT
    / "data"
    / "loreal-wmt-attributes"
    / "lorealpi_product_verification_input.xlsx"
)
DEFAULT_SKILL = ROOT / "agents" / "product-verification" / "SKILL.md"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "claude_runs"
OUTPUT_COLUMNS = ("Match Status", "Match Justification")

LONG_TEXT_LIMITS = {
    "Source_Feature_Bullets": 1200,
    "Source_Description": 1200,
    "Target_Description": 1200,
    "Target_Ingredients": 700,
}


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def safe_text(value: Any, *, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.active
    row_iter = worksheet.iter_rows(values_only=True)
    try:
        header_values = next(row_iter)
    except StopIteration:
        workbook.close()
        raise ValueError(f"Workbook had no rows: {path}")
    headers = [safe_text(value) for value in header_values]
    rows: list[dict[str, Any]] = []
    for row_idx, row_values in enumerate(row_iter):
        excel_row = row_idx + 2
        record: dict[str, Any] = {"row_idx": row_idx, "excel_row": excel_row}
        for col_idx, header in enumerate(headers):
            if not header or header in OUTPUT_COLUMNS:
                continue
            value = row_values[col_idx] if col_idx < len(row_values) else None
            text = safe_text(value, limit=LONG_TEXT_LIMITS.get(header))
            if text:
                record[header] = text
        rows.append(record)
    workbook.close()
    return headers, rows


def make_instruction(
    *,
    skill_path: Path,
    skill_text: str,
    input_workbook: Path,
    output_workbook: Path,
    batch_index: int,
    batch_rows: list[dict[str, Any]],
) -> str:
    expected_indices = [row["row_idx"] for row in batch_rows]
    payload = compact_json(batch_rows)
    return f"""# Claude Product Verification Batch {batch_index:03d}

You are running one batch of a product verification job.

Important: do not run tools, do not read the workbook, and do not write files for this batch. The workbook rows you need are already included below as JSON. Your only job is to reason over each row and return valid JSON.

Audit paths:
- Skill file: {skill_path}
- Input workbook: {input_workbook}
- Final output workbook planned by merge script: {output_workbook}

## Skill Rules

Follow these product verification rules exactly:

```markdown
{skill_text}
```

## Output Contract

Return only valid JSON. Do not include markdown, prose, code fences, or comments.

Use this compact schema exactly:

```json
[[row_idx,status_code,justification],...]
```

Rules:
- Include every expected `row_idx` exactly once.
- Do not include any `row_idx` outside this batch.
- `row_idx` is the zero-based data-row index from the workbook, not the Excel row number.
- `status_code` must be `"E"` for Exact, `"Q"` for Equivalent, or `"N"` for Not a Match.
- Use an empty string justification for Exact rows.
- For Equivalent and Not a Match rows, include a concise specific justification.
- Make the match decision yourself from the row evidence. Do not invent a rule-based shortcut such as UPC-only matching.

Expected row_idx values:

```json
{compact_json(expected_indices)}
```

Batch rows:

```json
{payload}
```
"""


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare timestamped Claude -p product verification batches.")
    parser.add_argument("--input-workbook", type=Path, default=DEFAULT_INPUT_WORKBOOK)
    parser.add_argument("--skill", type=Path, default=DEFAULT_SKILL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--row-start", type=int, default=0, help="Zero-based data-row index to start from.")
    parser.add_argument("--row-limit", type=int, help="Maximum number of data rows to include.")
    parser.add_argument("--run-id", help="Optional run id. Defaults to run_YYYYMMDD_HHMMSS.")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    input_workbook = args.input_workbook.resolve()
    skill_path = args.skill.resolve()
    if not input_workbook.exists():
        raise FileNotFoundError(input_workbook)
    if not skill_path.exists():
        raise FileNotFoundError(skill_path)

    run_id = args.run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = (args.output_root / run_id).resolve()
    instruction_dir = run_dir / "instructions"
    payload_dir = run_dir / "payloads"
    raw_dir = run_dir / "raw_responses"
    result_dir = run_dir / "results"
    final_dir = run_dir / "final"
    for directory in (instruction_dir, payload_dir, raw_dir, result_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=True)

    headers, rows = load_rows(input_workbook)
    selected_rows = [row for row in rows if row["row_idx"] >= args.row_start]
    if args.row_limit is not None:
        selected_rows = selected_rows[: args.row_limit]

    skill_text = skill_path.read_text(encoding="utf-8")
    output_workbook = final_dir / "lorealpi_product_verification_claude_p_output.xlsx"

    batches: list[dict[str, Any]] = []
    for batch_index, start in enumerate(range(0, len(selected_rows), args.batch_size)):
        batch_rows = selected_rows[start : start + args.batch_size]
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
                "row_idx_start": batch_rows[0]["row_idx"],
                "row_idx_end": batch_rows[-1]["row_idx"],
                "row_count": len(batch_rows),
                "instruction_path": str(instruction_path),
                "payload_path": str(payload_path),
                "raw_response_path": str(raw_response_path),
                "result_path": str(result_path),
                "expected_row_idx": [row["row_idx"] for row in batch_rows],
            }
        )

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "input_workbook": str(input_workbook),
        "skill_path": str(skill_path),
        "output_workbook": str(output_workbook),
        "batch_size": args.batch_size,
        "row_start": args.row_start,
        "row_limit": args.row_limit,
        "total_workbook_data_rows": len(rows),
        "selected_data_rows": len(selected_rows),
        "headers": headers,
        "batches": batches,
    }
    write_json(run_dir / "manifest.json", manifest)

    print(f"Prepared {len(batches)} batches in {run_dir}")
    print(f"Manifest: {run_dir / 'manifest.json'}")
    print(f"Output workbook will be: {output_workbook}")


if __name__ == "__main__":
    main()
