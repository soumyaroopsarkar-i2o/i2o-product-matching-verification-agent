from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl


STATUS_KEYS = {
    "Exact": "exact",
    "Equivalent": "equivalent",
    "Not a Match": "not_match",
}


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def preview_row(row_number: int, row: tuple[Any, ...], header_map: dict[str, int]) -> dict[str, str | int]:
    def get(column: str) -> str:
        index = header_map.get(column)
        if index is None or index >= len(row):
            return ""
        return safe_text(row[index])

    return {
        "row": row_number,
        "sourceTitle": get("Source_Title"),
        "targetTitle": get("Target_Title"),
        "matchStatus": get("Match Status"),
        "matchJustification": get("Match Justification"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a verified product matching workbook for the UI.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.workbook, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = worksheet.iter_rows(values_only=True)
    headers = [safe_text(value) for value in next(rows)]
    header_map = {header: index for index, header in enumerate(headers) if header}
    status_index = header_map.get("Match Status")

    if status_index is None:
        raise ValueError("Output workbook does not contain Match Status.")

    counts: Counter[str] = Counter()
    previews: dict[str, dict[str, Any]] = {
        "all": {"label": "All", "rows": []},
        "exact": {"label": "Exact Match", "rows": []},
        "equivalent": {"label": "Equivalent Match", "rows": []},
        "not_match": {"label": "Not a Match", "rows": []},
    }

    for zero_index, row in enumerate(rows):
        excel_row = zero_index + 2
        status = safe_text(row[status_index] if status_index < len(row) else "")
        if not status:
            continue

        key = STATUS_KEYS.get(status)
        if not key:
            continue

        counts[status] += 1
        item = preview_row(excel_row, row, header_map)
        if len(previews["all"]["rows"]) < args.limit:
            previews["all"]["rows"].append(item)
        if len(previews[key]["rows"]) < args.limit:
            previews[key]["rows"].append(item)

    workbook.close()

    metrics = [
        {"key": "not_match", "label": "Not a Match", "value": counts["Not a Match"]},
        {"key": "exact", "label": "Exact Match", "value": counts["Exact"]},
        {"key": "equivalent", "label": "Equivalent Match", "value": counts["Equivalent"]},
    ]

    print(
        json.dumps(
            {
                "total": sum(counts.values()),
                "metrics": metrics,
                "preview": previews,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
