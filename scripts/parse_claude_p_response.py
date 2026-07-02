from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


STATUS_MAP = {
    "E": "Exact",
    "Q": "Equivalent",
    "N": "Not a Match",
}
REVERSE_STATUS_MAP = {value.upper(): key for key, value in STATUS_MAP.items()}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text_any_encoding(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_json_array(text: str) -> Any:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("No JSON array found in raw response")
    return json.loads(stripped[start : end + 1])


def normalize_decision(item: Any) -> tuple[int, str, str, str | None]:
    warning = None
    if isinstance(item, list) and len(item) == 3:
        row_idx, status_code, justification = item
    elif isinstance(item, dict):
        row_idx = item.get("row_idx")
        status_code = item.get("status_code", item.get("status"))
        justification = item.get("justification", "")
    else:
        raise ValueError(f"Invalid decision item: {item!r}")

    if not isinstance(row_idx, int):
        raise ValueError(f"Invalid row_idx in decision: {item!r}")

    status_code = str(status_code).strip().upper()
    status_code = REVERSE_STATUS_MAP.get(status_code, status_code)
    if status_code not in STATUS_MAP:
        raise ValueError(f"Invalid status_code in decision: {item!r}")

    justification = "" if justification is None else str(justification).strip()
    if status_code == "E" and justification:
        warning = f"Blanked non-empty Exact justification for row_idx {row_idx}"
        justification = ""
    if status_code != "E" and not justification:
        raise ValueError(f"Missing justification for non-Exact decision: {item!r}")

    return row_idx, status_code, justification, warning


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
    warnings = []
    seen: set[int] = set()
    for item in parsed:
        row_idx, status_code, justification, warning = normalize_decision(item)
        if warning:
            warnings.append(warning)
        if row_idx in seen:
            raise ValueError(f"Duplicate row_idx {row_idx} in batch {batch_index:03d}")
        seen.add(row_idx)
        decisions.append(
            {
                "row_idx": row_idx,
                "status_code": status_code,
                "status": STATUS_MAP[status_code],
                "justification": justification,
            }
        )

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
        "warnings": warnings,
        "decisions": decisions,
    }
    write_json(result_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse and validate cached Claude -p raw responses.")
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
        warning_count = len(result["warnings"])
        warning_text = f", {warning_count} warnings" if warning_count else ""
        print(f"Parsed batch {batch_index:03d}: {result['row_count']} rows{warning_text}")

    if not parsed:
        print("No raw response files found to parse.")


if __name__ == "__main__":
    main()
