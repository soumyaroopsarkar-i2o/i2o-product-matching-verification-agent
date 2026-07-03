import math
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from _paths import DATA_DIR

INPUT = DATA_DIR / "lorealpi_product_verification_input.csv"
OUTPUT = DATA_DIR / "lorealpi_product_verification_verified_output.csv"

STOPWORDS = {
    "a",
    "and",
    "bottle",
    "by",
    "for",
    "free",
    "fl",
    "fluid",
    "in",
    "may",
    "of",
    "oz",
    "ounce",
    "ounces",
    "pack",
    "packaging",
    "quality",
    "salon",
    "the",
    "vary",
    "vegan",
    "with",
}


def text(value):
    if pd.isna(value):
        return ""
    return str(value)


def normalize(value):
    value = text(value).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value):
    return {token for token in normalize(value).split() if token and token not in STOPWORDS}


def ratio(left, right):
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def jaccard(left, right):
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def extract_sizes(value):
    value = normalize(value)
    found = []

    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(fl\s*oz|oz|ounce|ounces|ml|g)\b", value):
        unit = unit.replace(" ", "_")
        found.append((float(amount), unit))

    for amount in re.findall(r"pack\s*of\s*(\d+)|(\d+)\s*(?:count|ct)\b", value):
        count = next((part for part in amount if part), None)
        if count:
            found.append((float(count), "count"))

    return found


def same_brand(source_brand, target_brand):
    source = normalize(source_brand)
    target = normalize(target_brand)
    if not source or not target:
        return False
    return source == target or source in target or target in source


def price_float(value):
    if pd.isna(value):
        return math.nan
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return math.nan


def size_differs(source_title, target_title):
    source_sizes = extract_sizes(source_title)
    target_sizes = extract_sizes(target_title)
    if not source_sizes or not target_sizes:
        return False

    source_set = {(round(amount, 2), unit) for amount, unit in source_sizes}
    target_set = {(round(amount, 2), unit) for amount, unit in target_sizes}
    return source_set != target_set


def verify_row(row):
    source_title = text(row.get("Source_Title"))
    target_title = text(row.get("Target_Title"))
    source_brand = text(row.get("Source_Brand"))
    target_brand = text(row.get("Target_Brand"))

    if not target_title:
        return "Not a Match", "Missing target product title."

    brand_ok = same_brand(source_brand, target_brand)
    title_ratio = ratio(source_title, target_title)
    token_score = jaccard(source_title, target_title)

    if not brand_ok and title_ratio < 0.72:
        return "Not a Match", "Different brand or product line."

    if title_ratio >= 0.72 or token_score >= 0.5:
        if size_differs(source_title, target_title):
            return "Equivalent", "Different size or pack count between source and target."

        source_price = price_float(row.get("Source_Price"))
        target_price = price_float(row.get("Target_Price"))
        source_currency = text(row.get("Source_Currency"))
        target_currency = text(row.get("Target_Currency"))
        if (
            not math.isnan(source_price)
            and not math.isnan(target_price)
            and source_price > 0
            and target_price > 0
            and source_currency == target_currency
            and (target_price < source_price * 0.70 or target_price > source_price * 1.30)
        ):
            delta = abs(target_price - source_price) / source_price
            direction = "above" if target_price > source_price else "below"
            return "Equivalent", f"Price anomaly: target price is {delta:.0%} {direction} source price."

        return "Exact", ""

    if brand_ok and (title_ratio >= 0.52 or token_score >= 0.33):
        return "Equivalent", "Same brand/product family, but title details differ."

    return "Not a Match", "Different product, variant, shade, or formulation."


def main():
    df = pd.read_csv(INPUT)
    decisions = df.apply(verify_row, axis=1, result_type="expand")
    df["Match Status"] = decisions[0]
    df["Match Justification"] = decisions[1]
    df.to_csv(OUTPUT, index=False)
    print(f"Wrote {OUTPUT}")
    print(df["Match Status"].value_counts().to_string())


if __name__ == "__main__":
    main()

