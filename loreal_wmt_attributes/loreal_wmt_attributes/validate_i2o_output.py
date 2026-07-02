from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parent.parent
INPUT_XLSX = ROOT / "lorealpi_product_verification_output_final.xlsx"
OUTPUT_CSV = ROOT / "lorealpi_product_verification_output_final_i2o.csv"

EXPECTED_COLUMNS = [
    "product_code",
    "customer_name",
    "region",
    "source_product_url",
    "UPC",
    "product_title",
    "platform",
    "match_status",
    "platform_product_url",
    "platform_identifier",
    "status_code",
    "input_created_on",
]


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def main() -> None:
    with OUTPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        csv_columns = reader.fieldnames or []

    wb = openpyxl.load_workbook(INPUT_XLSX, read_only=True, data_only=True)
    ws = wb["Product Verification"]
    rows = ws.iter_rows(values_only=True)
    headers = list(next(rows))
    idx = {name: i for i, name in enumerate(headers) if name}

    source_statuses = Counter()
    source_non_walmart = 0
    source_match_rows = 0
    for row in rows:
        seller = clean(row[idx["Target_Seller"]]).lower()
        status = clean(row[idx["Match Status"]])
        source_statuses[status] += 1
        if seller not in {"walmart", "walmart.com"}:
            source_non_walmart += 1
        if status in {"Exact", "Equivalent"} and seller in {"walmart", "walmart.com"}:
            source_match_rows += 1
    wb.close()

    print(f"csv_columns_ok={csv_columns == EXPECTED_COLUMNS}")
    print(f"csv_rows={len(csv_rows)}")
    print(f"expected_rows_from_workbook={source_match_rows}")
    print(f"source_statuses={dict(source_statuses)}")
    print(f"source_non_walmart={source_non_walmart}")
    print(f"csv_platforms={sorted({row['platform'] for row in csv_rows})}")
    print(f"csv_statuses={dict(Counter(row['match_status'] for row in csv_rows))}")
    print(f"csv_status_codes={sorted({row['status_code'] for row in csv_rows})}")
    print(f"csv_input_created_on={sorted({row['input_created_on'] for row in csv_rows})}")
    print(f"first_row={csv_rows[0] if csv_rows else {}}")
    print(f"last_row={csv_rows[-1] if csv_rows else {}}")


if __name__ == "__main__":
    main()
