import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir =
  "C:/Users/SoumyaroopSarkar/Downloads/i2o_product_matching_verification_agent/outputs/historical_pricing_live_url_review_20260630_0000";
const outputXlsx = path.join(outputDir, "confirmed_mismatches_simple.xlsx");

const rows = [
  [
    "79656050820",
    "326237366361",
    "2x Banana Boat Kids Max Protect & Play SPF 100 Clear Sunscreen Spray 6 oz",
    "Ebay",
    "https://www.ebay.com/itm/326237366361",
    "Kroger",
    "https://www.kroger.com/p/banana-boat-kids-max-protect-play-sunscreen-spray-spf-100-tear-free-sting-free/0007965605082",
  ],
  [
    "76828047237",
    "B081J5X5MM",
    "Wet Ones 24 ct Pack of 4",
    "Amazon",
    "https://www.amazon.com/dp/B081J5X5MM",
    "Target",
    "https://www.target.com/p/wet-ones-antibacterial-hand-wipes-singles-fresh-scent-24ct/-/A-13397720?clkid=3c241355Nfe6e11f080c7b938af543c2c&cpng=PTID1&TCID=AFL-3c241355Nfe6e11f080c7b938af543c2c&afsrc=1&lnm=201333&afid=Barcode%20Lookup&ref=tgt_adv_xasd0002",
  ],
  [
    "76828048647",
    "B087MSLC8J",
    "Wet Ones Tropical Splash 20 ct Travel Wipes, 30 pack",
    "Amazon",
    "https://www.amazon.com/dp/B087MSLC8J",
    "Walmart",
    "https://www.walmart.com/ip/WETONE-TROPICAL-20CT/50346192",
  ],
  [
    "76828048630",
    "B087MS4BWK",
    "Wet Ones Sensitive Skin 20 ct Travel Wipes, 30 pack",
    "Amazon",
    "https://www.amazon.com/dp/B087MS4BWK",
    "Kroger",
    "https://www.kroger.com/p/wet-ones-hand-wipes-for-sensitive-skin-extra-gentle-travel-pack/0007682804863",
  ],
  [
    "76828046704",
    "356592294560",
    "Wet Ones Sensitive Skin Wipes, 40 ct, 6 pack",
    "Ebay",
    "https://www.ebay.com/itm/356592294560",
    "Amazon",
    "https://www.amazon.com/dp/B0014D2DA2",
  ],
  [
    "79656000085",
    "236335159127",
    "4 Pack Banana Boat Moisturizing After Sun Lotion, 16 fl oz",
    "Ebay",
    "https://www.ebay.com/itm/236335159127",
    "Amazon",
    "https://www.amazon.com/dp/B010D05WSG",
  ],
  [
    "79656031652",
    "376642202155",
    "Banana Boat Sunscreen SPF 30 Ultra Sport 6 oz Spray, 6 Pack",
    "Ebay",
    "https://www.ebay.com/itm/376642202155",
    "Walmart",
    "https://www.walmart.com/ip/Banana-Boat-Sport-Ultra-SPF-30-Sunscreen-Spray-Twin-Pack-Spray-Sunscreen-Adult-Sunblock-6-oz-each/24287696",
  ],
  [
    "76828048432",
    "405885585377",
    "6 Pack Wet Ones Hand Wipes Fresh Scent 20 Count Each Travel Pack",
    "Ebay",
    "https://www.ebay.com/itm/405885585377",
    "Kroger",
    "https://www.kroger.com/p/wet-ones-hand-wipes-fresh-scent-antibacterial-travel-pack/0007682804843",
  ],
  [
    "79656025804",
    "236372332585",
    "Banana Boat Sport Kids Sunscreen Spray SPF 50 Twin Pack, PACK OF 2 TOTAL 4",
    "Ebay",
    "https://www.ebay.com/itm/236372332585",
    "Amazon",
    "https://www.amazon.com/dp/B07CLCVB5P",
  ],
];

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Confirmed Mismatches");
sheet.showGridLines = false;

const values = [
  [
    "UPC",
    "platform_identifier",
    "product_title",
    "marketplace",
    "anomaly_url",
    "median_range_marketplace",
    "median_range_url",
  ],
  ...rows,
];

sheet.getRangeByIndexes(0, 0, values.length, values[0].length).values = values;

const header = sheet.getRange("A1:G1");
header.format.fill.color = "#1F4E78";
header.format.font.color = "#FFFFFF";
header.format.font.bold = true;
header.format.horizontalAlignment = "center";
header.format.wrapText = true;

const table = sheet.getRangeByIndexes(0, 0, values.length, values[0].length);
table.format.font.name = "Aptos";
table.format.font.size = 10;
table.format.verticalAlignment = "top";

sheet.getRange("A:A").format.columnWidth = 15;
sheet.getRange("B:B").format.columnWidth = 20;
sheet.getRange("C:C").format.columnWidth = 55;
sheet.getRange("D:D").format.columnWidth = 14;
sheet.getRange("E:E").format.columnWidth = 45;
sheet.getRange("F:F").format.columnWidth = 24;
sheet.getRange("G:G").format.columnWidth = 55;
sheet.getRange("C:G").format.wrapText = true;
sheet.freezePanes.freezeRows(1);

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({
  sheetName: "Confirmed Mismatches",
  range: "A1:G10",
  autoCrop: "all",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "confirmed_mismatches_simple_preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(outputXlsx);
