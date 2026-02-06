# PdfWatcher

Windows desktop app that watches PDF/XML/BOLETO folders and moves files to company-specific destinations (MVA/HORIZONTE), organized by year/month. Includes Gmail draft creation, detailed logs, reports, and auto‑update via GitHub Releases.

## Features

- Watches separate source folders for PDF, XML, and BOLETO.
- Moves files to MVA or HORIZONTE destinations.
- Creates destination structure by date (PDF/XML: `YYYY/MONTH`; BOLETO: `MM-YYYY`).
- PySide6 UI (no Tkinter, no web).
- Tray icon with quick actions.
- Persistent configuration in `%APPDATA%\\PdfWatcher\\config.json`.
- Gmail draft creation and sent‑check to avoid duplicates.
- Detailed debug log + report view.
- Auto update via GitHub Releases (prompts before updating).

## Requirements

- Windows
- Python 3.13 64‑bit (recommended)

## Quick setup (venv)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

- With tray:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py
```

- Console only:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --no-tray
```

- Open configuration UI only:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --config
```

- Open logs UI only:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --logs
```

## Build EXE (PyInstaller)

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\pyinstaller PdfWatcher.spec
```

Expected output: `dist/PdfWatcher.exe`

## Auto update (GitHub Releases)

1. Set the repo in Config (e.g. `AlleexMartinsT/AutoWriter`).
2. Publish a GitHub Release with a `.exe` asset.
3. The app will prompt to update, download the new EXE, replace the current one, and restart.

## Optional environment variables

- `PDF_NOME`
- `PDF_PATTERN`
- `PDF_TEXT_MATCH_MVA`
- `PDF_TEXT_MATCH_HORIZONTE`
- `XML_CNPJ_MVA`
- `XML_CNPJ_HORIZONTE`
- `PDF_ALLOW_ALL`
- `PDF_POLL_INTERVAL`
- `PDF_CACHE_TTL`
- `PDF_LOG_PATH`
- `PDF_DEBUG_LOG_PATH`
- `PDF_REPORT_PATH`
- `PDF_REPORT_STATE_PATH`
- `UPDATE_CHECK_INTERVAL` (seconds)

## Key files

- `downloads_pdf_mover.py` — main app + UI.
- `PdfWatcher.spec` — PyInstaller build spec.
- `requirements.txt` — runtime dependencies.
- `requirements-dev.txt` — build dependencies.
