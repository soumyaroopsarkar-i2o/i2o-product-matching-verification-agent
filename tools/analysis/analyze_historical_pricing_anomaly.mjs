import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "C:/Users/SoumyaroopSarkar/Downloads/Historical Pricing_06-29-26.xlsx";
const outputDir = "C:/Users/SoumyaroopSarkar/Downloads/i2o_product_matching_verification_agent/outputs/historical_pricing_anomaly_20260629_2052";
const outputPath = path.join(outputDir, "Historical Pricing_06-29-26_marketplace_anomaly_output.xlsx");

const MARKETPLACE_COLUMNS = [
  "Amazon Buy Box Price",
  "Walmart Buy Box Price",
  "Target Buy Box Price",
  "Ebay Buy Box Price",
  "Cvs Buy Box Price",
  "Walgreens Buy Box Price",
  "Ulta Buy Box Price",
  "Samsclub Buy Box Price",
  "Kroger Buy Box Price",
  "Iherb Buy Box Price",
  "Meijer Buy Box Price",
  "Heb Buy Box Price",
];

function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) && value > 0 ? value : null;
  const cleaned = String(value).replace(/[^0-9.,-]/g, "");
  if (!cleaned) return null;
  const parsed = Number(cleaned.replace(/,/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function marketplaceName(header) {
  return header.replace(/\s+Buy Box Price$/i, "");
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function quantile(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] === undefined ? sorted[base] : sorted[base] + rest * (sorted[base + 1] - sorted[base]);
}

function pct(value) {
  return value === null || value === undefined || !Number.isFinite(value) ? "" : value;
}

function money(value) {
  return value === null || value === undefined || !Number.isFinite(value) ? "" : value;
}

function classifyCandidate(observations) {
  if (observations.length <= 2) {
    return {
      marketplace: "",
      price: "",
      peerMedian: "",
      pctVsPeerMedian: "",
      confidence: "Skipped",
      reason: `Only ${observations.length} usable marketplace prices; requires at least 3.`,
    };
  }

  const scored = observations.map((obs) => {
    const peers = observations.filter((other) => other.marketplace !== obs.marketplace).map((other) => other.price);
    const peerMedian = median(peers);
    const pctDiff = peerMedian ? obs.price / peerMedian - 1 : 0;
    const logDistance = Math.abs(Math.log(obs.price / peerMedian));
    const peerMin = Math.min(...peers);
    const peerMax = Math.max(...peers);
    const peerSpread = peerMin > 0 ? peerMax / peerMin - 1 : Infinity;
    const q1 = quantile(peers, 0.25);
    const q3 = quantile(peers, 0.75);
    const iqrRatio = peerMedian ? (q3 - q1) / peerMedian : Infinity;
    return { ...obs, peerMedian, pctDiff, logDistance, peerSpread, iqrRatio };
  }).sort((a, b) => b.logDistance - a.logDistance);

  const top = scored[0];
  const second = scored[1];
  const absPct = Math.abs(top.pctDiff);
  const separation = top.logDistance - (second?.logDistance ?? 0);
  const peerClustered = top.peerSpread <= 0.45 || top.iqrRatio <= 0.22;
  const veryLargeMove = absPct >= 0.75;
  const largeMove = absPct >= 0.40;
  const moderateMove = absPct >= 0.30;

  let confidence = "No clear single anomaly";
  if ((veryLargeMove && separation >= 0.18) || (largeMove && separation >= 0.14 && peerClustered)) {
    confidence = "High";
  } else if ((largeMove && separation >= 0.08) || (moderateMove && separation >= 0.12 && peerClustered)) {
    confidence = "Review";
  }

  if (confidence === "No clear single anomaly") {
    return {
      marketplace: "",
      price: "",
      peerMedian: median(observations.map((obs) => obs.price)),
      pctVsPeerMedian: "",
      confidence,
      reason: `No single marketplace separated enough from the product's price distribution (${observations.length} usable prices).`,
      usableMarketplaces: observations.length,
      minPrice: Math.min(...observations.map((obs) => obs.price)),
      maxPrice: Math.max(...observations.map((obs) => obs.price)),
    };
  }

  const direction = top.pctDiff > 0 ? "above" : "below";
  const reason = `${top.marketplace} price ${money(top.price).toFixed(2)} is ${(Math.abs(top.pctDiff) * 100).toFixed(1)}% ${direction} peer median ${money(top.peerMedian).toFixed(2)}; peer spread excluding it is ${(top.peerSpread * 100).toFixed(1)}%.`;
  return {
    marketplace: top.marketplace,
    price: top.price,
    peerMedian: top.peerMedian,
    pctVsPeerMedian: top.pctDiff,
    confidence,
    reason,
    usableMarketplaces: observations.length,
    minPrice: Math.min(...observations.map((obs) => obs.price)),
    maxPrice: Math.max(...observations.map((obs) => obs.price)),
  };
}

function asRows(headers, values) {
  return values.slice(1).map((row, idx) => {
    const record = { __rowNumber: idx + 2 };
    headers.forEach((header, colIdx) => {
      record[header] = row[colIdx] ?? null;
    });
    return record;
  });
}

function colLetter(indexOneBased) {
  let n = indexOneBased;
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - m) / 26);
  }
  return s;
}

function writeMatrix(sheet, startRow, startCol, matrix) {
  if (!matrix.length || !matrix[0].length) return;
  const range = sheet.getRangeByIndexes(startRow, startCol, matrix.length, matrix[0].length);
  range.values = matrix;
}

function styleTable(sheet, rowCount, colCount) {
  const header = sheet.getRangeByIndexes(0, 0, 1, colCount);
  header.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).format.borders = {
    preset: "inside",
    style: "thin",
    color: "#D9E2EF",
  };
  sheet.freezePanes.freezeRows(1);
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).format.autofitColumns();
  sheet.getRangeByIndexes(0, 0, rowCount, colCount).format.autofitRows();
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });

  const input = await FileBlob.load(inputPath);
  const sourceWorkbook = await SpreadsheetFile.importXlsx(input);
  const sourceSheet = sourceWorkbook.worksheets.getItem("Historical Pricing");
  const values = sourceSheet.getRange("A1:R82").values;
  const headers = values[0];
  const sourceRows = asRows(headers, values);

  const marketplaceIndexes = MARKETPLACE_COLUMNS
    .map((header) => ({ header, index: headers.indexOf(header) }))
    .filter((item) => item.index >= 0);

  const details = sourceRows.map((row) => {
    const observations = marketplaceIndexes
      .map(({ header }) => ({
        marketplace: marketplaceName(header),
        price: toNumber(row[header]),
      }))
      .filter((obs) => obs.price !== null);
    const decision = classifyCandidate(observations);
    return { row, observations, decision };
  });

  const flagged = details
    .filter(({ decision }) => decision.marketplace)
    .map(({ row, decision }) => ({
      UPC: row.UPC,
      Timestamp: row["D&T(Rounded)"],
      "Marketplace Having Anomaly": decision.marketplace,
      "Anomaly Price": decision.price,
      "Peer Median": decision.peerMedian,
      "% vs Peer Median": decision.pctVsPeerMedian,
      Confidence: decision.confidence,
      "Usable Marketplace Prices": decision.usableMarketplaces,
      "Min Product Price": decision.minPrice,
      "Max Product Price": decision.maxPrice,
      "Price Anomaly Justification": decision.reason,
      MAP: row.MAP,
      "Amazon BBx Status": row["Amazon Current BBx Status"],
      "Current BBx Winner": row["Current BBx Winner"],
    }));

  const allRows = details.map(({ row, decision }) => ({
    ...row,
    marketplace_having_anomaly: decision.marketplace,
    anomaly_price: decision.price,
    peer_median_price: decision.peerMedian,
    pct_vs_peer_median: decision.pctVsPeerMedian,
    anomaly_confidence: decision.confidence,
    usable_marketplace_prices: decision.usableMarketplaces,
    product_min_price: decision.minPrice,
    product_max_price: decision.maxPrice,
    "price anomaly justification": decision.reason,
  }));

  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const detail = workbook.worksheets.add("Annotated Data");
  summary.showGridLines = false;
  detail.showGridLines = false;

  const totalRows = sourceRows.length;
  const eligibleRows = details.filter(({ decision }) => decision.confidence !== "Skipped").length;
  const highRows = flagged.filter((row) => row.Confidence === "High").length;
  const reviewRows = flagged.filter((row) => row.Confidence === "Review").length;

  const summaryIntro = [
    ["Historical Pricing Marketplace Anomaly Summary", ""],
    ["Input workbook", inputPath],
    ["Method", "Stage 2B-style row-level marketplace price outlier detection by UPC. Uses positive buy-box prices only and requires at least 3 marketplaces."],
    ["Total product rows", totalRows],
    ["Rows with 3+ usable marketplace prices", eligibleRows],
    ["Flagged marketplace-product combos", flagged.length],
    ["High confidence", highRows],
    ["Review", reviewRows],
    ["Generated", `Generated at ${new Date().toISOString()}`],
    ["", ""],
  ];
  writeMatrix(summary, 0, 0, summaryIntro);
  summary.getRange("A1:B1").merge();
  summary.getRange("A1").format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF", size: 14 },
  };
  summary.getRange("A2:A9").format = { font: { bold: true }, fill: "#EAF2F8" };
  summary.getRange("B2:B9").format = { wrapText: true };

  const flaggedHeaders = Object.keys(flagged[0] ?? {
    UPC: "",
    Timestamp: "",
    "Marketplace Having Anomaly": "",
    "Anomaly Price": "",
    "Peer Median": "",
    "% vs Peer Median": "",
    Confidence: "",
    "Usable Marketplace Prices": "",
    "Min Product Price": "",
    "Max Product Price": "",
    "Price Anomaly Justification": "",
    MAP: "",
    "Amazon BBx Status": "",
    "Current BBx Winner": "",
  });
  const flaggedMatrix = [flaggedHeaders, ...flagged.map((row) => flaggedHeaders.map((header) => row[header] ?? ""))];
  writeMatrix(summary, 10, 0, flaggedMatrix);
  styleTable(summary, flaggedMatrix.length + 10, flaggedHeaders.length);
  summary.getRangeByIndexes(10, 0, 1, flaggedHeaders.length).format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  summary.getRange("D12:E100").format.numberFormat = "$#,##0.00";
  summary.getRange("F12:F100").format.numberFormat = "0.0%";
  summary.getRange("I12:J100").format.numberFormat = "$#,##0.00";
  summary.getRange("K:K").format.wrapText = true;

  const allHeaders = Object.keys(allRows[0] ?? {});
  const allMatrix = [allHeaders, ...allRows.map((row) => allHeaders.map((header) => row[header] ?? ""))];
  writeMatrix(detail, 0, 0, allMatrix);
  styleTable(detail, allMatrix.length, allHeaders.length);
  const firstAnomalyCol = headers.length + 1;
  const lastCol = allHeaders.length;
  detail.getRange(`${colLetter(firstAnomalyCol)}1:${colLetter(lastCol)}1`).format = {
    fill: "#806000",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  for (const header of MARKETPLACE_COLUMNS) {
    const idx = allHeaders.indexOf(header);
    if (idx >= 0) {
      detail.getRange(`${colLetter(idx + 1)}2:${colLetter(idx + 1)}${allMatrix.length}`).format.numberFormat = "$#,##0.00";
    }
  }
  for (const header of ["anomaly_price", "peer_median_price", "product_min_price", "product_max_price"]) {
    const idx = allHeaders.indexOf(header);
    if (idx >= 0) detail.getRange(`${colLetter(idx + 1)}2:${colLetter(idx + 1)}${allMatrix.length}`).format.numberFormat = "$#,##0.00";
  }
  const pctIdx = allHeaders.indexOf("pct_vs_peer_median");
  if (pctIdx >= 0) detail.getRange(`${colLetter(pctIdx + 1)}2:${colLetter(pctIdx + 1)}${allMatrix.length}`).format.numberFormat = "0.0%";

  const summaryPreview = await workbook.render({ sheetName: "Summary", autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, "summary_preview.png"), new Uint8Array(await summaryPreview.arrayBuffer()));
  const detailPreview = await workbook.render({ sheetName: "Annotated Data", range: "A1:AB25", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, "annotated_preview.png"), new Uint8Array(await detailPreview.arrayBuffer()));

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);

  const manifest = {
    inputPath,
    outputPath,
    totalRows,
    eligibleRows,
    flaggedRows: flagged.length,
    highRows,
    reviewRows,
    topFindings: flagged.slice(0, 20),
    formulaErrorScan: "Workbook contains no formulas; computed anomaly columns are static analysis outputs.",
  };
  await fs.writeFile(path.join(outputDir, "run_summary.json"), JSON.stringify(manifest, null, 2), "utf8");
  console.log(JSON.stringify(manifest, null, 2));
}

await main();
