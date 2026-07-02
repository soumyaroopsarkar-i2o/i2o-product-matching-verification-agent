---
name: price-anomaly-verification
description: Second-pass verification for product match spreadsheets. Use after product-verification has produced match statuses, when the task is to review only Exact matches, compare available comparable marketplace prices, flag +/-30% price divergence, recheck equivalence, and identify the marketplace listing with the least common/outlier price.
---

# Price Anomaly Verification

Run after first-pass product verification. Review first-pass `Exact` rows for pairwise price divergence and reclassify only `Exact -> Equivalent` cases.

## Hard Gates

Apply these gates in order before any price reasoning.

### 1. Exact Rows Only

Process a row only when the first-pass status column says `Exact` case-insensitively.

Accepted status columns, in order:

1. `Match Status`
2. `match_status`
3. `Verification Status`
4. `verification_status`
5. A clearly equivalent first-pass verification status column

Skip immediately as `Skipped - Not Exact` when the status is `Equivalent`, `Not a Match`, blank, missing, pending, uncertain, failed, or anything other than `Exact`. Do not inspect prices for skipped non-Exact rows.

If no first-pass status column can be identified, stop and ask the user which column defines `Exact`.

### 2. Pairwise Prices Only

Process an `Exact` row only when both pair prices are present and comparable.

A usable price must be present, numeric, greater than zero, and represent final selling price. Reject placeholders, ranges, discounts, ratings, list prices, shipping fees, membership-only prices, subscription prices, coupons, and malformed values.

Prices are comparable only when currency and unit basis match, or when a reliable normalized unit price can be calculated from explicit quantity data. Do not compare across different currencies, pack sizes, counts, weights, volumes, bundles, variants, shades, scents, flavors, formulations, or unclear unit bases.

Skip as `Skipped - No Comparable Pair Prices` when either side of the pair lacks a usable comparable price. Never guess missing prices, currency, or quantity.

## Pairwise Price Check

Normalize prices only when currency and unit basis are clear. Record the basis used, such as `raw price`, `price per each`, `price per oz`, `price per ml`, or `price per count`.

For the source-target pair:

- Compare `Source_Price` and `Target_Price`.
- Use the source price as baseline.
- Flag an anomaly when target price is below `baseline * 0.70` or above `baseline * 1.30`.

If the pair is within +/-30%, mark `No Price Anomaly` and stop.

## Recheck Flagged Pair

For every pairwise price anomaly, recheck whether the source and target are still equivalent using product facts, not price alone.

Check brand, title, product line, identifiers, pack size, count, weight, volume, bundle size, variant, shade, scent, flavor, formulation, seller context, URL, images, and descriptions when available.

If the pair is not equivalent, classify as `Price Anomaly - Possible Mismatch` or `Price Anomaly - Recheck Needed`.

If the pair is equivalent, return an equivalent price-anomaly decision. The merge script will fill `reclassified_status = Equivalent`.

Do not perform marketplace group/outlier analysis.

Classify the final case as:

- `Price Anomaly - Equivalent`: pair is equivalent and one marketplace/listing is the price outlier.
- `Price Anomaly - Possible Mismatch`: product evidence suggests different product, variant, size, formulation, shade, scent, flavor, model, category, or product line.
- `Price Anomaly - Recheck Needed`: price diverges, but evidence or marketplace comparison is insufficient.

Do not downgrade or overwrite the original `Match Status` unless the user explicitly asks.

## Output Columns

Preserve all original rows and columns. Append or update these columns:

1. `reclassified_status`

Fill `reclassified_status` only when this stage changes a first-pass `Exact` row to an equivalent price anomaly. Leave it blank for all other rows.

Do not add price-reason, divergence, marketplace, or outlier columns.

## Workflow

1. Open the workbook and locate first-pass match results.
2. Add the output columns if missing.
3. Apply `Exact` gate. Skip all non-Exact rows without price review.
4. Check whether both pair prices are present and comparable.
5. Compare the pair with the +/-30% rule.
6. If the pair does not diverge, leave `reclassified_status` blank and stop.
7. If the pair diverges, recheck whether the pair is equivalent.
8. If equivalent, set `reclassified_status = Equivalent`.
9. Save a new output workbook unless the user asks to overwrite.
