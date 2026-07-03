import csv
from datetime import datetime
from pathlib import Path

from _paths import DATA_DIR
from zoneinfo import ZoneInfo


BASE = DATA_DIR
AMAZON_CSV = BASE / "loreal_amazon_match.csv"
WALMART_CSV = BASE / "loreal_walmart_match.csv"
OUT_CSV = BASE / "lorealpi_amazon_source_walmart_target_enriched.csv"

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

SOURCE_ALIASES = {
    "EACH UPC": "UPC",
    "ASIN": "Input_ASIN",
    "asin": "ASIN",
    "parent_asin": "Parent_ASIN",
    "source": "Data_Source",
    "matched": "Matched",
}

TARGET_ALIASES = {
    "EACH UPC": "UPC",
    "ASIN": "Input_ASIN",
    "matched": "Matched",
}


def clean(value):
    return (value or "").strip()


def truthy(value):
    return clean(value).lower() in {"true", "1", "yes", "y"}


def amazon_url(asin):
    return f"https://www.amazon.com/dp/{asin}" if asin else ""


def prefixed_name(prefix, col, aliases, used):
    name = f"{prefix}_{aliases.get(col, col)}"
    name = "_".join(name.replace("/", "_").replace("-", "_").split())
    base = name
    idx = 2
    while name.lower() in used:
        name = f"{base}_{idx}"
        idx += 1
    used.add(name.lower())
    return name


def build_column_map(prefix, columns, aliases):
    used = {col.lower() for col in I2O_COLUMNS}
    return {col: prefixed_name(prefix, col, aliases, used) for col in columns}


def prefixed(row, column_map):
    return {out_col: clean(row.get(src_col)) for src_col, out_col in column_map.items()}


def main():
    with AMAZON_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        amazon_reader = csv.DictReader(f)
        amazon_columns = amazon_reader.fieldnames or []
        source_column_map = build_column_map("Source", amazon_columns, SOURCE_ALIASES)
        amazon_by_upc = {
            clean(row.get("EACH UPC")): row
            for row in amazon_reader
            if clean(row.get("EACH UPC"))
        }

    with WALMART_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        walmart_reader = csv.DictReader(f)
        walmart_columns = walmart_reader.fieldnames or []
        target_column_map = build_column_map("Target", walmart_columns, TARGET_ALIASES)
        output_columns = (
            I2O_COLUMNS
            + list(source_column_map.values())
            + list(target_column_map.values())
        )

        rows = []
        total_walmart_rows = 0
        walmart_matches = 0
        skipped_no_source_asin = 0
        skipped_no_walmart_url = 0
        run_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%m-%Y")

        for target in walmart_reader:
            total_walmart_rows += 1
            if not truthy(target.get("matched")):
                continue
            walmart_matches += 1

            upc = clean(target.get("EACH UPC"))
            source = amazon_by_upc.get(upc, {})
            source_asin = clean(target.get("ASIN")) or clean(source.get("asin")) or clean(source.get("ASIN"))
            if not source_asin:
                skipped_no_source_asin += 1
                continue

            target_url = clean(target.get("walmart_link"))
            if not target_url:
                skipped_no_walmart_url += 1
                continue

            source_url = clean(source.get("amazon_link")) or amazon_url(source_asin)
            source_title = clean(source.get("amazon_title"))
            target_title = clean(target.get("walmart_title"))
            product_title = source_title or clean(target.get("EMD")) or target_title

            out = {
                "product_code": source_asin,
                "customer_name": "lorealpi",
                "region": "us",
                "source_product_url": source_url,
                "UPC": upc,
                "product_title": product_title,
                "platform": "walmart.com",
                "match_status": "Exact Match",
                "platform_product_url": target_url,
                "platform_identifier": clean(target.get("walmart_item_id"))
                or clean(target.get("walmart_product_id")),
                "status_code": "200",
                "input_created_on": run_date,
            }
            out.update(prefixed(source, source_column_map))
            out.update(prefixed(target, target_column_map))
            rows.append(out)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"total_walmart_rows={total_walmart_rows}")
    print(f"walmart_matches={walmart_matches}")
    print(f"written_rows={len(rows)}")
    print(f"skipped_no_source_asin={skipped_no_source_asin}")
    print(f"skipped_no_walmart_url={skipped_no_walmart_url}")
    print(f"columns={len(output_columns)}")
    print(f"output={OUT_CSV}")


if __name__ == "__main__":
    main()

