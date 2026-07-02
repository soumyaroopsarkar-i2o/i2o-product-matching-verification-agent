import csv
from datetime import date
from pathlib import Path


BASE = Path(__file__).parent
WALMART_CSV = BASE / "loreal_walmart_match.csv"
AMAZON_CSV = BASE / "loreal_amazon_match.csv"
OUT_CSV = BASE / "lorealpi_amazon_to_walmart_i2o_matches_with_titles.csv"

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
    "amazon_title",
    "walmart_title",
]


def clean(value):
    return (value or "").strip()


def truthy(value):
    return clean(value).lower() in {"true", "1", "yes", "y"}


def amazon_url(asin):
    return f"https://www.amazon.com/dp/{asin}" if asin else ""


def load_amazon_by_upc():
    by_upc = {}
    with AMAZON_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            upc = clean(row.get("EACH UPC"))
            asin = clean(row.get("asin")) or clean(row.get("ASIN"))
            if not upc or not asin:
                continue
            by_upc[upc] = {
                "asin": asin,
                "amazon_link": clean(row.get("amazon_link")) or amazon_url(asin),
                "amazon_title": clean(row.get("amazon_title")),
            }
    return by_upc


def main():
    amazon_by_upc = load_amazon_by_upc()
    rows = []
    total_walmart_rows = 0
    walmart_matches = 0
    skipped_no_source_asin = 0
    skipped_no_walmart_url = 0
    run_date = date.today().strftime("%d-%m-%Y")

    with WALMART_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total_walmart_rows += 1
            if not truthy(row.get("matched")):
                continue
            walmart_matches += 1

            upc = clean(row.get("EACH UPC"))
            amazon = amazon_by_upc.get(upc, {})
            source_asin = clean(row.get("ASIN")) or amazon.get("asin", "")
            if not source_asin:
                skipped_no_source_asin += 1
                continue

            walmart_url = clean(row.get("walmart_link"))
            if not walmart_url:
                skipped_no_walmart_url += 1
                continue

            source_url = amazon.get("amazon_link") or amazon_url(source_asin)
            product_title = (
                amazon.get("amazon_title")
                or clean(row.get("EMD"))
                or clean(row.get("walmart_title"))
            )
            walmart_title = clean(row.get("walmart_title"))

            rows.append(
                {
                    "product_code": source_asin,
                    "customer_name": "lorealpi",
                    "region": "us",
                    "source_product_url": source_url,
                    "UPC": upc,
                    "product_title": product_title,
                    "platform": "walmart.com",
                    "match_status": "Exact Match",
                    "platform_product_url": walmart_url,
                    "platform_identifier": clean(row.get("walmart_item_id"))
                    or clean(row.get("walmart_product_id")),
                    "status_code": "200",
                    "input_created_on": run_date,
                    "amazon_title": amazon.get("amazon_title", ""),
                    "walmart_title": walmart_title,
                }
            )

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=I2O_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"total_walmart_rows={total_walmart_rows}")
    print(f"walmart_matches={walmart_matches}")
    print(f"written_rows={len(rows)}")
    print(f"skipped_no_source_asin={skipped_no_source_asin}")
    print(f"skipped_no_walmart_url={skipped_no_walmart_url}")
    print(f"output={OUT_CSV}")


if __name__ == "__main__":
    main()
