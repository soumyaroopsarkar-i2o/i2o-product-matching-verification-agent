import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "loreal_wmt_attributes" / "loreal_wmt_attributes" / "lorealpi_product_verification_verified_output.csv"
DEST = ROOT / "verification-ui" / "public" / "mock-results"

FILES = {
    "all": "all_results.csv",
    "exact": "exact_matches.csv",
    "equivalent": "equivalent_matches.csv",
    "not_match": "not_a_match.csv",
}

PREVIEW_COLUMNS = ["Source_Title", "Target_Title", "Match Status", "Match Justification"]


def status_key(status):
    return {
        "Exact": "exact",
        "Equivalent": "equivalent",
        "Not a Match": "not_match",
    }[status]


def preview_rows(df, limit=8):
    rows = []
    for index, row in df.head(limit).iterrows():
        rows.append(
            {
                "row": int(index + 1),
                "sourceTitle": "" if pd.isna(row["Source_Title"]) else str(row["Source_Title"]),
                "targetTitle": "" if pd.isna(row["Target_Title"]) else str(row["Target_Title"]),
                "matchStatus": "" if pd.isna(row["Match Status"]) else str(row["Match Status"]),
                "matchJustification": "" if pd.isna(row["Match Justification"]) else str(row["Match Justification"]),
            }
        )
    return rows


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SOURCE)

    df.to_csv(DEST / FILES["all"], index=False)

    counts = df["Match Status"].value_counts().to_dict()
    filters = {"all": df}
    for status in ["Exact", "Equivalent", "Not a Match"]:
        key = status_key(status)
        filtered = df[df["Match Status"] == status]
        filters[key] = filtered
        filtered.to_csv(DEST / FILES[key], index=False)

    summary = {
        "total": int(len(df)),
        "files": FILES,
        "metrics": [
            {"key": "not_match", "label": "Not a Match", "value": int(counts.get("Not a Match", 0))},
            {"key": "exact", "label": "Exact Match", "value": int(counts.get("Exact", 0))},
            {"key": "equivalent", "label": "Equivalent Match", "value": int(counts.get("Equivalent", 0))},
        ],
    }

    preview = {
        key: {
            "label": "All Results" if key == "all" else summary_label,
            "rows": preview_rows(value[PREVIEW_COLUMNS].reset_index(drop=True)),
        }
        for key, value, summary_label in [
            ("all", filters["all"], "All Results"),
            ("not_match", filters["not_match"], "Not a Match"),
            ("exact", filters["exact"], "Exact Match"),
            ("equivalent", filters["equivalent"], "Equivalent Match"),
        ]
    }

    (DEST / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (DEST / "preview.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")
    print(f"Wrote mock results to {DEST}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
