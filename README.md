# i2o Product Matching Verification Agent

Workbook-based product matching verification pipeline with a React review UI and Codex/Claude agent instructions.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `apps/verification-ui` | React/Vite UI and Node backend for running verification jobs. |
| `agents/product-verification` | First-pass product match verification skill and agent config. |
| `agents/price-anomaly-detection` | Second-pass price anomaly verification skill and agent config. |
| `workflows/verification` | Production batch preparation, parsing, merge, and orchestration scripts. |
| `tools/analysis` | One-off and historical analysis utilities. |
| `tools/loreal-wmt-attributes` | L'Oreal/Walmart data preparation and collection utilities. |
| `docs` | Architecture and operating notes. |
| `data/loreal-wmt-attributes` | Local ignored workbooks, CSVs, caches, and generated data files. |
| `outputs` | Local ignored pipeline outputs. |

## Main Workflow

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File workflows\verification\run_full_verification_flow.ps1 `
  -InputWorkbook data\loreal-wmt-attributes\lorealpi_product_verification_input.xlsx `
  -BatchSize 100
```

The workflow defaults to `data/loreal-wmt-attributes/lorealpi_product_verification_input.xlsx` when no input workbook is provided.

## UI

Double-click `start-verification-ui.bat` from the repository root to install missing UI dependencies, start the backend, start the frontend, and open the app in your browser.

The app opens at:

```text
http://127.0.0.1:5173
```

Backend health check:

```text
http://127.0.0.1:5175/api/health
```

Manual startup is also available:

```powershell
cd apps\verification-ui
pnpm install
pnpm run backend
pnpm run dev
```

The backend uses scripts from `workflows/verification` and stores UI runtime state under `apps/verification-ui/server-data`.
