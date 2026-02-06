# PdfWatcher

Aplicacao para monitorar pastas de PDF/XML e mover arquivos automaticamente para destinos separados (MVA e HORIZONTE), com organizacao por ano/mes.

## Funcionalidades

- Monitora origem de PDF e XML separadamente.
- Move PDF e XML para destinos separados por empresa.
- Cria estrutura automatica `ANO/MES` no destino.
- Interface de configuracao com **PySide6** (sem Tkinter e sem web).
- Icone na bandeja com opcao **Configurar pastas**.
- Configuracao persistida em `%APPDATA%\\PdfWatcher\\config.json`.

## Requisitos

- Windows
- Python 3.13 64-bit (recomendado)

## Setup rapido (venv)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Execucao

- Rodar com tray:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py
```

- Rodar sem tray (console):

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --no-tray
```

- Abrir somente a tela de configuracao:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --config
```

## Build EXE (PyInstaller)

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\pyinstaller PdfWatcher.spec
```

Saida esperada: `dist/PdfWatcher.exe`

## Variaveis de ambiente opcionais

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

## Estrutura principal

- `downloads_pdf_mover.py` -> monitor e UI de configuracao.
- `PdfWatcher.spec` -> build com PyInstaller.
- `requirements.txt` -> dependencias de execucao.
- `requirements-dev.txt` -> dependencias de build.
