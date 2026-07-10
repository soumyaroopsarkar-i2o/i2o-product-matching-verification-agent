---
name: product-verification
description: Verify product matches in spreadsheet files. Use when the user mentions product matching verification, product match QA, verifying matched products, QAing matched listings, checking whether product pairs match, or asks to run product-verification on a file. Do not use for general product search, price comparison, product categorization, or finding new product matches.
---

# Product Verification

Verify each source product against its matched target product in the supplied spreadsheet, then populate two output columns while preserving every original column and row.

## Spreadsheet Output

Before creating any `.xlsx` output, read `/mnt/skills/public/xlsx/SKILL.md` when that path exists in the runtime. If it is unavailable, use the best available spreadsheet tooling while preserving workbook structure, columns, data, and formatting as much as possible.

Populate these columns:

- Column 33, `Match Status`: one of `Exact`, `Equivalent`, or `Not a Match`
- Column 34, `Match Justification`: blank for `Exact`; required for `Equivalent` and `Not a Match`

If the columns already exist, update them. If they are missing, add them after column 32.

## Column Layout

Source product columns 1-15:

1. `Source_ASIN`
2. `Source_UPC`
3. `Source_URL`
4. `Source_Brand`
5. `Source_Title`
6. `Source_Category`
7. `Source_Rating`
8. `Source_Ratings_Total`
9. `Source_Price`
10. `Source_Currency`
11. `Source_Seller`
12. `Source_Search_Alias`
13. `Source_Feature_Bullets`
14. `Source_Description`
15. `Source_Image_URL`

Target product columns 16-32:

16. `Target_Platform`
17. `Target_Item_ID`
18. `Target_Product_ID`
19. `Target_URL`
20. `Target_Brand`
21. `Target_Title`
22. `Target_Model`
23. `Target_Type`
24. `Target_Category`
25. `Target_Rating`
26. `Target_Ratings_Total`
27. `Target_Price`
28. `Target_Currency`
29. `Target_Seller`
30. `Target_Description`
31. `Target_Ingredients`
32. `Target_Image_URL`

## Match Rules

Review each product pair manually using judgment. Use all available evidence: titles, brands, UPCs, ASINs, model/product IDs, descriptions, feature bullets, ingredients, categories, URLs, image URLs, price, currency, and seller context.

Before confirming any row, use the browser tool to visit each available `Source_URL` and `Target_URL`. Inspect the live product pages for title, brand, model, size/count, variant, condition, seller/listing context, and product images. Use the row evidence plus the browser findings for the final decision. If a URL is unavailable, inaccessible, or clearly not a product page, continue with the available evidence and do not treat the missing page as proof of a match.

Assign `Exact` when the source and target are the same product and the quantity, count, weight, volume, pack size, shade, formulation, and variant are also the same.

Assign `Equivalent` when the source and target are the same product but quantity, count, weight, volume, pack size, or bundle size differs.

Assign `Not a Match` when the target is a different product, different variant, different shade/color, different formulation, different scent/flavor, different model, incompatible category, or any other mismatch.

Strict condition rule: classify the row as `Not a Match` if either listing is refurbished, renewed, rebuilt, reconditioned, open-box, used, pre-owned, or otherwise not a new retail product. This applies even when the brand, model, UPC, or visible product identity otherwise matches.

## Price Anomaly Rule

After deciding that a row would otherwise be `Exact`, compare price only when both prices are present, nonzero, and use the same currency.

If `Target_Price` is outside `[Source_Price * 0.70, Source_Price * 1.30]`, downgrade the row to `Equivalent` and write a justification such as `Price anomaly: Target_Price is 42% below Source_Price`.

Skip the price anomaly check when either price is missing, zero, or in a different currency.

## Workflow

1. Open the workbook and identify the sheet or sheets containing the product match rows.
2. For each row, visit the available source and target URLs with the browser tool before confirming the classification.
3. Mark `Exact`, `Equivalent`, or `Not a Match`.
4. Leave `Match Justification` blank for `Exact`.
5. For `Equivalent`, explain the quantity or price difference concisely.
6. For `Not a Match`, explain the product, variant, formulation, shade, model, or category mismatch concisely.
7. Save a new spreadsheet result unless the user explicitly asks to overwrite the original file.

## Justification Style

Keep justifications short and specific:

- `Different pack size: source is 12 oz, target is 8 oz.`
- `Price anomaly: Target_Price is 35% above Source_Price.`
- `Different shade: source is Soft Black, target is Medium Brown.`
- `Different formulation: source is shampoo, target is conditioner.`
- `Different product line despite same brand.`
