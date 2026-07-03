import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir =
  "C:/Users/SoumyaroopSarkar/Downloads/i2o_product_matching_verification_agent/outputs/historical_pricing_live_url_review_20260630_0000";
const sourceXlsx = path.join(
  outputDir,
  "high_price_live_url_product_review_chrome_rechecked_final.xlsx",
);
const outputXlsx = path.join(
  outputDir,
  "high_price_live_url_product_review_with_median_match_column.xlsx",
);

const sourceBlob = await FileBlob.load(sourceXlsx);
const sourceWorkbook = await SpreadsheetFile.importXlsx(sourceBlob);
const sourceSheet = sourceWorkbook.worksheets.getItemAt(0);
const sourceValues = sourceSheet.getUsedRange(true).values;

if (sourceValues.length < 2) {
  throw new Error("Source CSV does not contain data rows.");
}

const headers = sourceValues[0].map((value, index) => {
  const text = String(value ?? "");
  return index === 0 ? text.replace(/^\uFEFF/, "") : text;
});
const headerIndex = Object.fromEntries(headers.map((header, index) => [header, index]));

const requiredHeaders = [
  "comparison_marketplace_within_30pct_of_median",
  "comparison_product_code",
  "comparison_price",
  "comparison_title",
  "comparison_url",
];
const missingHeaders = requiredHeaders.filter((header) => !(header in headerIndex));
if (missingHeaders.length > 0) {
  throw new Error(`Missing expected source columns: ${missingHeaders.join(", ")}`);
}

const insertedHeader = "same_product_in_other_marketplace_within_median_price";
const insertAfterHeader = "final_review_basis";
const insertAt =
  insertAfterHeader in headerIndex ? headerIndex[insertAfterHeader] + 1 : headers.length;

const asText = (value) => String(value ?? "").trim();
const asCurrency = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `$${numeric.toFixed(2)}` : asText(value);
};

const buildMedianMatch = (row) => {
  const marketplace = asText(row[headerIndex.comparison_marketplace_within_30pct_of_median]);
  const productCode = asText(row[headerIndex.comparison_product_code]);
  const price = asCurrency(row[headerIndex.comparison_price]);
  const title = asText(row[headerIndex.comparison_title]);
  const url = asText(row[headerIndex.comparison_url]);

  const parts = [];
  if (marketplace) parts.push(`Marketplace: ${marketplace}`);
  if (productCode) parts.push(`Platform identifier: ${productCode}`);
  if (price) parts.push(`Price: ${price}`);
  if (title) parts.push(`Title: ${title}`);
  if (url) parts.push(`URL: ${url}`);

  return parts.join(" | ");
};

const outputValues = sourceValues.map((row, rowIndex) => {
  const newCell = rowIndex === 0 ? insertedHeader : buildMedianMatch(row);
  return [...row.slice(0, insertAt), newCell, ...row.slice(insertAt)];
});

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Review With Median Match");
sheet.showGridLines = false;

const rowCount = outputValues.length;
const colCount = outputValues[0].length;
sheet.getRangeByIndexes(0, 0, rowCount, colCount).values = outputValues;

const allRange = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
allRange.format.font.name = "Aptos";
allRange.format.font.size = 10;
allRange.format.verticalAlignment = "top";

const headerRange = sheet.getRangeByIndexes(0, 0, 1, colCount);
headerRange.format.fill.color = "#1F4E78";
headerRange.format.font.color = "#FFFFFF";
headerRange.format.font.bold = true;
headerRange.format.wrapText = true;
headerRange.format.horizontalAlignment = "center";
headerRange.format.rowHeight = 42;

const dataRange = sheet.getRangeByIndexes(1, 0, rowCount - 1, colCount);
dataRange.format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
};

sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(3);

const insertedRange = sheet.getRangeByIndexes(0, insertAt, rowCount, 1);
insertedRange.format.fill.color = "#FFF2CC";
insertedRange.format.wrapText = true;
insertedRange.format.columnWidth = 80;

const finalReviewCol = headers.indexOf("final_same_product_review");
if (finalReviewCol >= 0) {
  sheet.getRangeByIndexes(0, finalReviewCol, rowCount, 1).format.columnWidth = 32;
}

const likelyWideHeaders = [
  "final_review_basis",
  "high_price_title",
  "comparison_title",
  "high_price_url",
  "comparison_url",
  "chrome_high_page_title",
  "chrome_comparison_page_title",
  "chrome_high_h1",
  "chrome_comparison_h1",
  "live_high_all_signals",
  "live_comparison_all_signals",
];

for (const header of likelyWideHeaders) {
  const originalIndex = headers.indexOf(header);
  if (originalIndex < 0) continue;
  const adjustedIndex = originalIndex >= insertAt ? originalIndex + 1 : originalIndex;
  const columnRange = sheet.getRangeByIndexes(0, adjustedIndex, rowCount, 1);
  columnRange.format.wrapText = true;
  columnRange.format.columnWidth = header.includes("url") ? 52 : 44;
}

const priceHeaders = ["high_price", "peer_median", "comparison_price"];
for (const header of priceHeaders) {
  const originalIndex = headers.indexOf(header);
  if (originalIndex < 0) continue;
  const adjustedIndex = originalIndex >= insertAt ? originalIndex + 1 : originalIndex;
  sheet.getRangeByIndexes(1, adjustedIndex, rowCount - 1, 1).setNumberFormat("$0.00");
}

const pctHeaders = ["high_price_pct_vs_median", "comparison_pct_vs_median"];
for (const header of pctHeaders) {
  const originalIndex = headers.indexOf(header);
  if (originalIndex < 0) continue;
  const adjustedIndex = originalIndex >= insertAt ? originalIndex + 1 : originalIndex;
  sheet.getRangeByIndexes(1, adjustedIndex, rowCount - 1, 1).setNumberFormat("0.0%");
}

sheet.getRangeByIndexes(1, 0, rowCount - 1, colCount).format.rowHeight = 58;

await fs.mkdir(outputDir, { recursive: true });

const preview = await workbook.render({
  sheetName: "Review With Median Match",
  range: "A1:J15",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "high_price_live_url_product_review_with_median_match_column_preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const check = await workbook.inspect({
  kind: "table",
  range: "Review With Median Match!A1:E6",
  include: "values",
  tableMaxRows: 6,
  tableMaxCols: 5,
  tableMaxCellChars: 140,
  maxChars: 4000,
});
console.log(check.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(outputXlsx);
