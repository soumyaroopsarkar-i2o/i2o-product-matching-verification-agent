from __future__ import annotations

import csv
from pathlib import Path

from _paths import DATA_DIR

import openpyxl


BASE = DATA_DIR
ROOT = DATA_DIR
INPUT_XLSX = ROOT / "lorealpi_product_verification_output_final.xlsx"
OUTPUT_CSV = ROOT / "lorealpi_product_verification_output_final_i2o.csv"

SHEET_NAME = "Product Verification"
INPUT_CREATED_ON = "27-05-2026"

I2O_COLUMNS = [
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

STATUS_MAP = {
    "Exact": "Exact Match",
    "Equivalent": "Equivalent Match",
}


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def header_map(headers: list) -> dict[str, int]:
    return {clean(name): idx for idx, name in enumerate(headers) if clean(name)}


def row_value(row: tuple, headers: dict[str, int], name: str) -> str:
    return clean(row[headers[name]])


def is_walmart_seller(value: str) -> bool:
    seller = clean(value).lower()
    return seller in {"walmart", "walmart.com"} or seller.startswith("walmart.com ")


def convert() -> tuple[int, int, int]:
    wb = openpyxl.load_workbook(INPUT_XLSX, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    rows = ws.iter_rows(values_only=True)
    headers = header_map(list(next(rows)))

    output_rows = []
    dropped_not_match = 0
    skipped_non_walmart = 0

    for row in rows:
        status = row_value(row, headers, "Match Status")
        mapped_status = STATUS_MAP.get(status)
        if not mapped_status:
            dropped_not_match += 1
            continue

        if not is_walmart_seller(row_value(row, headers, "Target_Seller")):
            skipped_non_walmart += 1
            continue

        output_rows.append(
            {
                "product_code": row_value(row, headers, "Source_ASIN"),
                "customer_name": "lorealpi",
                "region": "us",
                "source_product_url": row_value(row, headers, "Source_URL"),
                "UPC": row_value(row, headers, "Source_UPC"),
                "product_title": row_value(row, headers, "Source_Title"),
                "platform": "walmart.com",
                "match_status": mapped_status,
                "platform_product_url": row_value(row, headers, "Target_URL"),
                "platform_identifier": row_value(row, headers, "Target_Item_ID"),
                "status_code": 200,
                "input_created_on": INPUT_CREATED_ON,
            }
        )

    wb.close()

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=I2O_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    return len(output_rows), dropped_not_match, skipped_non_walmart


def main() -> None:
    written, dropped_not_match, skipped_non_walmart = convert()
    print(f"output={OUTPUT_CSV}")
    print(f"written_rows={written}")
    print(f"dropped_not_match_rows={dropped_not_match}")
    print(f"skipped_non_walmart_rows={skipped_non_walmart}")


if __name__ == "__main__":
    main()

