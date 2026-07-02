from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
INPUT_XLSX = ROOT / "lorealpi_upc_20260527_075445_walmart_unmatched_upcs_all_marketplaces.xlsx"
OUTPUT_CSV = ROOT / "lorealpi_product_verification_output_final_i2o.csv"

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

# Title-only review passed for these exact-match rows. UPC 800897275365 is excluded
# because the workbook row lacks source title/product_code/source URL evidence.
VERIFIED_EXACT_UPCS = {
    "800897254704",
    "800897274863",
    "800897274917",
    "800897274924",
    "800897274931",
    "800897274979",
    "800897274986",
    "800897274993",
    "800897275013",
    "800897275037",
    "800897275044",
    "800897275051",
    "800897275068",
    "800897275075",
    "800897275082",
    "800897275099",
    "800897275105",
    "800897275181",
    "800897275273",
    "800897275327",
    "800897275358",
    "800897275372",
    "800897275389",
    "800897275440",
    "800897275457",
    "800897275464",
    "800897275471",
    "800897275495",
    "800897275501",
    "800897275525",
    "800897275549",
    "800897275556",
    "800897275563",
    "800897275587",
    "800897275594",
    "800897275617",
    "800897275624",
    "800897275655",
    "800897279523",
    "800897279547",
    "800897279554",
    "800897284251",
    "800897284275",
    "800897284282",
    "800897284299",
    "800897284343",
    "800897284350",
    "800897284367",
    "800897284435",
}


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def main() -> None:
    source = pd.read_excel(INPUT_XLSX, sheet_name="matches", dtype=str)
    exact = source[source["match_status"].map(clean).eq("Exact_Match")].copy()

    exact["UPC"] = exact["UPC"].map(clean)
    verified = exact[exact["UPC"].isin(VERIFIED_EXACT_UPCS)].copy()
    skipped = exact[~exact["UPC"].isin(VERIFIED_EXACT_UPCS)].copy()

    required = [
        "product_code",
        "source_product_url",
        "UPC",
        "product_title",
        "platform_product_url",
        "platform_identifier",
    ]
    missing_required = verified[
        verified[required].apply(lambda col: col.map(clean).eq("")).any(axis=1)
    ]
    if not missing_required.empty:
        raise RuntimeError(
            "Verified rows unexpectedly have missing required fields: "
            + ", ".join(missing_required["UPC"].map(clean).tolist())
        )

    with OUTPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        existing_rows = list(reader)
        if reader.fieldnames != I2O_COLUMNS:
            raise RuntimeError(f"Unexpected output columns: {reader.fieldnames}")

    existing_keys = {
        (clean(row["product_code"]), clean(row["platform_identifier"]))
        for row in existing_rows
    }

    rows_to_append = []
    duplicate_keys = []
    for _, row in verified.iterrows():
        out = {
            "product_code": clean(row["product_code"]),
            "customer_name": clean(row["customer_name"]) or "lorealpi",
            "region": clean(row["region"]) or "us",
            "source_product_url": clean(row["source_product_url"]),
            "UPC": clean(row["UPC"]),
            "product_title": clean(row["product_title"]),
            "platform": clean(row["platform"]) or "walmart.com",
            "match_status": "Exact Match",
            "platform_product_url": clean(row["platform_product_url"]),
            "platform_identifier": clean(row["platform_identifier"]),
            "status_code": clean(row["status_code"]) or "200",
            "input_created_on": clean(row["input_created_on"]) or "27-05-2026",
        }
        key = (out["product_code"], out["platform_identifier"])
        if key in existing_keys:
            duplicate_keys.append(key)
            continue
        rows_to_append.append(out)

    backup = OUTPUT_CSV.with_name(
        f"{OUTPUT_CSV.stem}.backup-before-unmatched-append-{datetime.now():%Y%m%d_%H%M%S}.csv"
    )
    shutil.copy2(OUTPUT_CSV, backup)

    with OUTPUT_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=I2O_COLUMNS)
        writer.writerows(rows_to_append)

    print(f"input_exact_rows={len(exact)}")
    print(f"verified_title_rows={len(verified)}")
    print(f"skipped_unverified_exact_rows={len(skipped)}")
    if not skipped.empty:
        print("skipped_upcs=" + ",".join(skipped["UPC"].map(clean).tolist()))
    print(f"duplicate_rows_skipped={len(duplicate_keys)}")
    print(f"rows_appended={len(rows_to_append)}")
    print(f"backup={backup}")
    print(f"output={OUTPUT_CSV}")


if __name__ == "__main__":
    main()
