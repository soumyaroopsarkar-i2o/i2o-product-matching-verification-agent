from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "flat_marketplace_anomaly_runs"


STOP_WORDS = {
    "a",
    "an",
    "and",
    "broad",
    "by",
    "each",
    "for",
    "free",
    "from",
    "in",
    "may",
    "of",
    "on",
    "or",
    "packaging",
    "product",
    "spectrum",
    "the",
    "to",
    "vary",
    "water",
    "with",
}

FAMILY_PATTERNS = [
    ("wet ones", r"\bwet\s+ones\b"),
    ("schick intuition", r"\bintuition\b"),
    ("schick hydro silk", r"\bhydro\s+silk\b"),
    ("schick hydro", r"\bhydro\b"),
    ("schick xtreme", r"\bxtreme\s*\d?\b"),
    ("skintimate", r"\bskintimate\b"),
    ("billie", r"\bbillie\b"),
    ("banana boat", r"\bbanana\s+boat\b"),
    ("hawaiian tropic", r"\bhawaiian\s+tropic\b"),
]

FORM_PATTERNS = [
    ("wipes", r"\bwipes?\b"),
    ("body butter", r"\bbody\s+butter\b"),
    ("gel", r"\bgel\b"),
    ("spray", r"\b(?:spray|mist|ultramist|c[- ]?spray)\b"),
    ("lotion", r"\blotion\b"),
    ("oil", r"(?<!coconut )\boil\b"),
    ("stick", r"\bstick\b"),
    ("kit", r"\bkit\b"),
    ("refill", r"\b(?:refills?|cartridges?)\b"),
    ("disposable", r"\bdisposable\b"),
    ("dermaplane", r"\b(?:dermaplane|dermaplaning)\b"),
    ("razor", r"\brazors?\b"),
]

VARIANT_PATTERNS = [
    ("advanced moisture", r"\badvanced\s+moisture\b"),
    ("after sun", r"\bafter\s+sun\b"),
    ("dark tanning", r"\bdark\s+tanning\b"),
    ("dream pop", r"\bdream\s+pop\b"),
    ("dry skin", r"\bdry\s+skin\b"),
    ("everyday active", r"\beveryday\s+active\b"),
    ("fresh scent", r"\bfresh\s+scent\b"),
    ("fragrance free", r"\bfragrance\s+free\b"),
    ("fresh gardenia", r"\bfresh\s+gardenia\b"),
    ("island sport", r"\bisland\s+sport\b"),
    ("kids", r"\bkids?\b"),
    ("malibu", r"\bmalibu\b"),
    ("mineral", r"\bmineral\b"),
    ("moonbeam", r"\bmoonbeam\b"),
    ("pure nourishment", r"\bpure\s+nourishment\b"),
    ("sensitive", r"\bsensitive\b"),
    ("sheer touch", r"\bsheer\s+touch\b"),
    ("sport", r"\bsport\b"),
    ("tropical splash", r"\btropical\s+splash\b"),
    ("ultra", r"\bultra\b"),
    ("weightless hydration", r"\bweightless\s+hydration\b"),
]


def safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_text(value: Any) -> str:
    text = safe_text(value).lower().replace("\ufffd", " ")
    text = text.replace("&", " and ")
    text = re.sub(r"\s+-\s+[a-z0-9-]{7,}\s*$", " ", text)
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def display_title(row: dict[str, str]) -> str:
    return safe_text(row.get("product_title")) or safe_text(row.get("short_name"))


def token_set(value: str) -> set[str]:
    text = normalize_text(value)
    tokens = {token for token in re.findall(r"[a-z0-9.]+", text) if len(token) > 1}
    return {token for token in tokens if token not in STOP_WORDS}


def canonical_number(value: str) -> str:
    number = float(value)
    if math.isclose(number, round(number)):
        return str(int(round(number)))
    return f"{number:g}"


def extract_by_patterns(text: str, patterns: list[tuple[str, str]]) -> set[str]:
    return {name for name, pattern in patterns if re.search(pattern, text)}


def extract_features(title: str) -> dict[str, set[str]]:
    text = normalize_text(title)
    features: dict[str, set[str]] = {
        "family": extract_by_patterns(text, FAMILY_PATTERNS),
        "form": extract_by_patterns(text, FORM_PATTERNS),
        "variant": extract_by_patterns(text, VARIANT_PATTERNS),
        "spf": set(),
        "size": set(),
        "count": set(),
        "blade_count": set(),
    }

    spf_text = re.sub(r"\bno\s+spf\b", "nospf", text)
    for match in re.finditer(r"\bspf\s*[-:]?\s*(\d{1,3})\b", spf_text):
        features["spf"].add(match.group(1))

    for amount, unit in re.findall(
        r"\b(\d+(?:\.\d+)?)\s*(fl\s*oz|floz|oz|ounce|ounces|ml|g)\b",
        text,
    ):
        canonical_unit = "oz" if "oz" in unit or "ounce" in unit else unit.replace(" ", "")
        features["size"].add(f"{canonical_number(amount)} {canonical_unit}")

    for amount, unit in re.findall(r"\b(\d+(?:\.0)?)\s*(ct|count|pk|pack|packs|ea)\b", text):
        canonical_unit = "ct" if unit in {"ct", "count", "ea"} else "pack"
        features["count"].add(f"{canonical_number(amount)} {canonical_unit}")
    if re.search(r"\btwin\s+pack\b", text):
        features["count"].add("2 pack")

    for amount in re.findall(r"\b(\d+)[- ]?blade\b", text):
        features["blade_count"].add(f"{amount} blade")

    return features


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def common_values(peer_features: list[dict[str, set[str]]], key: str, threshold: float) -> set[str]:
    counter: collections.Counter[str] = collections.Counter()
    populated = 0
    for features in peer_features:
        values = features[key]
        if values:
            populated += 1
            counter.update(values)
    if not populated:
        return set()
    return {value for value, count in counter.items() if count / populated >= threshold}


def consensus_string(values: list[str]) -> tuple[str, float]:
    cleaned = [normalize_text(value) for value in values if safe_text(value)]
    if not cleaned:
        return "", 0.0
    value, count = collections.Counter(cleaned).most_common(1)[0]
    return value, count / len(cleaned)


def score_row(row: dict[str, Any], peers: list[dict[str, Any]]) -> tuple[float, str, list[str]]:
    peer_tokens = [peer["tokens"] for peer in peers]
    peer_features = [peer["features"] for peer in peers]
    similarities = [jaccard(row["tokens"], tokens) for tokens in peer_tokens]
    median_similarity = median(similarities) if similarities else 1.0

    score = max(0.0, (0.45 - median_similarity) * 80)
    reasons: list[str] = []
    severe_conflict = False

    if median_similarity < 0.25:
        score += 20
        reasons.append(f"low title similarity versus UPC peers (median {median_similarity:.2f})")
    elif median_similarity < 0.38:
        score += 8
        reasons.append(f"weaker title similarity versus UPC peers (median {median_similarity:.2f})")

    common_family = common_values(peer_features, "family", 0.60)
    row_family = row["features"]["family"]
    if common_family:
        missing = common_family - row_family
        conflicting = row_family - common_family
        if missing and conflicting:
            score += 55
            severe_conflict = True
            reasons.append(
                f"product family {sorted(conflicting)} conflicts with peer family {sorted(common_family)}"
            )
        elif missing:
            score += 16
            reasons.append(f"missing peer product family {sorted(common_family)}")

    common_form = common_values(peer_features, "form", 0.60)
    row_form = row["features"]["form"]
    form_conflicts = {
        "wipes": {"kit", "refill", "razor", "disposable", "dermaplane"},
        "kit": {"wipes", "lotion", "oil", "spray"},
        "refill": {"wipes", "lotion", "oil", "spray"},
        "spray": {"wipes", "kit", "refill"},
        "lotion": {"wipes", "kit", "refill"},
        "oil": {"wipes", "kit", "refill"},
    }
    if common_form:
        missing = common_form - row_form
        conflicting = {
            form
            for form in row_form
            if any(form in form_conflicts.get(peer_form, set()) for peer_form in common_form)
        }
        if conflicting:
            score += 36
            severe_conflict = True
            reasons.append(f"form {sorted(conflicting)} conflicts with peer form {sorted(common_form)}")
        elif missing and median_similarity < 0.35:
            score += 10
            reasons.append(f"missing common form {sorted(missing)}")

    for key, weight, threshold, label in [
        ("spf", 22, 0.70, "SPF"),
        ("size", 18, 0.70, "size"),
        ("count", 18, 0.65, "count/pack"),
        ("blade_count", 10, 0.70, "blade count"),
        ("variant", 10, 0.65, "variant"),
    ]:
        common = common_values(peer_features, key, threshold)
        if not common:
            continue
        missing = common - row["features"][key]
        conflicting = row["features"][key] - common
        if missing and conflicting:
            score += weight
            reasons.append(f"{label} {sorted(conflicting)} differs from peer majority {sorted(common)}")
        elif missing and median_similarity < 0.35:
            score += weight * 0.6
            reasons.append(f"missing peer-majority {label} {sorted(common)}")

    brand_consensus, brand_share = consensus_string([peer["raw"].get("brand", "") for peer in peers])
    row_brand = normalize_text(row["raw"].get("brand", ""))
    if brand_consensus and brand_share >= 0.70 and row_brand and row_brand != brand_consensus and median_similarity < 0.35:
        score += 8
        reasons.append(f"brand differs from peer majority ({safe_text(row['raw'].get('brand'))})")

    if severe_conflict:
        confidence = "High"
    elif score >= 70:
        confidence = "Review"
    elif score >= 48 and len(reasons) >= 2:
        confidence = "Review"
    else:
        confidence = "None"

    return score, confidence, reasons


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def peer_examples(group: list[dict[str, Any]], exclude_excel_row: int, limit: int = 3) -> str:
    counter = collections.Counter(
        item["title"] for item in group if item["excel_row"] != exclude_excel_row and item["title"]
    )
    return " ||| ".join(title for title, _ in counter.most_common(limit))


def analyze(headers: list[str], rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for zero_idx, raw in enumerate(rows):
        upc = safe_text(raw.get("upc"))
        if not upc:
            continue
        title = display_title(raw)
        groups[upc].append(
            {
                "zero_idx": zero_idx,
                "excel_row": zero_idx + 2,
                "raw": raw,
                "title": title,
                "tokens": token_set(title),
                "features": extract_features(title),
            }
        )

    decisions: list[dict[str, Any]] = []
    annotations: dict[int, dict[str, Any]] = {}
    eligible_groups = 0
    no_clear_groups = 0

    for upc, group in sorted(groups.items()):
        marketplaces = sorted({safe_text(item["raw"].get("marketplace")) for item in group if safe_text(item["raw"].get("marketplace"))})
        if len(group) < 3 or len(marketplaces) < 3:
            continue
        eligible_groups += 1

        scored: list[dict[str, Any]] = []
        for item in group:
            peers = [peer for peer in group if peer["excel_row"] != item["excel_row"]]
            score, confidence, reasons = score_row(item, peers)
            scored.append({**item, "score": score, "confidence": confidence, "reasons": reasons})

        scored.sort(key=lambda item: item["score"], reverse=True)
        top = scored[0]
        second_score = scored[1]["score"] if len(scored) > 1 else 0.0
        separated = top["score"] - second_score >= 8 or top["confidence"] == "High"
        if top["confidence"] == "None" or not separated:
            no_clear_groups += 1
            continue

        reason = "; ".join(top["reasons"][:4]) or "least consistent title/metadata in the UPC marketplace group"
        note = f"Adapted non-price Stage 2B run: {reason}"
        decision = {
            "upc": upc,
            "marketplace_having_anomaly": safe_text(top["raw"].get("marketplace")),
            "anomaly_excel_row": top["excel_row"],
            "product_code": safe_text(top["raw"].get("product_code")),
            "product_title": top["title"],
            "confidence": top["confidence"],
            "anomaly_score": round(top["score"], 1),
            "second_highest_score": round(second_score, 1),
            "peer_row_count": len(group),
            "peer_marketplace_count": len(marketplaces),
            "peer_marketplaces": ", ".join(marketplaces),
            "price anomaly justification": note,
            "peer_title_examples": peer_examples(group, top["excel_row"]),
        }
        decisions.append(decision)
        annotations[top["zero_idx"]] = decision

    positive_prices = 0
    for row in rows:
        try:
            if float(safe_text(row.get("catalog_price"))) > 0:
                positive_prices += 1
        except ValueError:
            pass

    stats = {
        "total_rows": len(rows),
        "total_upc_groups": len(groups),
        "eligible_upc_groups_with_3plus_marketplaces": eligible_groups,
        "groups_with_no_clear_single_anomaly": no_clear_groups,
        "flagged_groups": len(decisions),
        "flagged_high_confidence": sum(1 for item in decisions if item["confidence"] == "High"),
        "flagged_review": sum(1 for item in decisions if item["confidence"] == "Review"),
        "positive_catalog_price_rows": positive_prices,
        "catalog_price_note": "catalog_price was not used for anomaly scoring because usable positive prices were sparse.",
        "output_columns": [
            "marketplace_having_anomaly",
            "price anomaly justification",
            "listing_anomaly_confidence",
            "listing_anomaly_score",
            "peer_marketplace_count",
            "peer_row_count",
        ],
    }
    decisions.sort(key=lambda item: (item["confidence"] != "High", -item["anomaly_score"], item["upc"]))
    return decisions, annotations, stats


def write_outputs(
    input_path: Path,
    output_root: Path,
    headers: list[str],
    rows: list[dict[str, str]],
    decisions: list[dict[str, Any]],
    annotations: dict[int, dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    run_id = f"{input_path.stem}_flat_marketplace_anomaly_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / f"{input_path.stem}_marketplace_listing_anomaly_summary.csv"
    annotated_path = run_dir / f"{input_path.stem}_marketplace_listing_anomaly_output.csv"
    stats_path = run_dir / f"{input_path.stem}_marketplace_listing_anomaly_summary.json"

    summary_headers = [
        "upc",
        "marketplace_having_anomaly",
        "anomaly_excel_row",
        "product_code",
        "product_title",
        "confidence",
        "anomaly_score",
        "second_highest_score",
        "peer_row_count",
        "peer_marketplace_count",
        "peer_marketplaces",
        "price anomaly justification",
        "peer_title_examples",
    ]
    with summary_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(decisions)

    appended_headers = [
        "marketplace_having_anomaly",
        "price anomaly justification",
        "listing_anomaly_confidence",
        "listing_anomaly_score",
        "peer_marketplace_count",
        "peer_row_count",
    ]
    output_headers = headers + [header for header in appended_headers if header not in headers]
    with annotated_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_headers, extrasaction="ignore")
        writer.writeheader()
        for zero_idx, row in enumerate(rows):
            out = dict(row)
            decision = annotations.get(zero_idx)
            if decision:
                out["marketplace_having_anomaly"] = decision["marketplace_having_anomaly"]
                out["price anomaly justification"] = decision["price anomaly justification"]
                out["listing_anomaly_confidence"] = decision["confidence"]
                out["listing_anomaly_score"] = decision["anomaly_score"]
                out["peer_marketplace_count"] = decision["peer_marketplace_count"]
                out["peer_row_count"] = decision["peer_row_count"]
            else:
                for header in appended_headers:
                    out.setdefault(header, "")
            writer.writerow(out)

    stats = {
        **stats,
        "input_csv": str(input_path),
        "run_dir": str(run_dir),
        "summary_csv": str(summary_path),
        "annotated_csv": str(annotated_path),
    }
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(stats, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run adapted Stage 2B-style marketplace anomaly checks on a flat listing CSV.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()

    input_path = args.input_csv.resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    headers, rows = read_rows(input_path)
    decisions, annotations, stats = analyze(headers, rows)
    write_outputs(input_path, args.output_root.resolve(), headers, rows, decisions, annotations, stats)


if __name__ == "__main__":
    main()
