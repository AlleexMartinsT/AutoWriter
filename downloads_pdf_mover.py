import os
import time
import shutil
import re
import sys
import json
import zipfile
import threading
import argparse
import unicodedata
import subprocess
import mimetypes
import base64
from email.message import EmailMessage
from datetime import datetime
import ctypes
import urllib.request
import urllib.error
import ssl
import tempfile
from pathlib import Path

MESES = [
    "JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"
]

APP_NAME = "PdfWatcher"
CONFIG_FILE_NAME = "config.json"
NFES_PACOTE_RE = re.compile(r"nfes\s*-\s*\d+\s*-\s*\d+", re.IGNORECASE)
APP_VERSION = "1.2.10"
GITHUB_REPO = "AlleexMartinsT/AutoWriter"


def _default_paths(base_dir: Path) -> dict[str, str]:
    downloads = Path(os.getenv("USERPROFILE", str(base_dir))) / "Downloads"
    return {
        "pdf_watch_dir": str(downloads),
        "xml_watch_dir": str(downloads),
        "boleto_watch_dir": str(downloads),
        "pdf_destino_mva": r"Z:\CAIXA\PDF VENDAS 2026",
        "pdf_destino_horizonte": r"\\192.168.1.240\eh\CAIXA PDF-XML-BOLETOS ELE. HORIZONTE\PDF VENDAS 2026",
        "xml_destino_mva": r"Z:\CAIXA\XML VENDAS 2026",
        "xml_destino_horizonte": r"\\192.168.1.240\eh\CAIXA PDF-XML-BOLETOS ELE. HORIZONTE\XML VENDAS 2026",
        "boleto_destino_mva": r"Z:\CAIXA\BOLETOS\BOLETOS 2026",
        "boleto_destino_horizonte": r"\\192.168.1.240\eh\CAIXA PDF-XML-BOLETOS ELE. HORIZONTE\BOLETOS 2026",
        "email_enabled": "0",
        "debug_enabled": "0",
        "auto_update_enabled": "1",
    }


def _config_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    config_dir = appdata / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / CONFIG_FILE_NAME


def _log_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_LOG_PATH", str(appdata / "PdfWatcher" / "logs" / "watcher.log")))

def _debug_log_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_DEBUG_LOG_PATH", str(appdata / "PdfWatcher" / "logs" / "watcher_debug.log")))

def _report_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_REPORT_PATH", str(appdata / "PdfWatcher" / "logs" / "report.txt")))

def _report_state_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_REPORT_STATE_PATH", str(appdata / "PdfWatcher" / "report_state.json")))

def _viewer_settings_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_VIEWER_SETTINGS_PATH", str(appdata / "PdfWatcher" / "viewer_settings.json")))


def _status_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_STATUS_PATH", str(appdata / "PdfWatcher" / "status.json")))


def _status_padrao() -> dict[str, object]:
    return {
        "busy": False,
        "phase": "Parado",
        "detail": "Aguardando inicialização.",
        "scan_interval_seconds": 2,
        "last_cycle_seconds": 0.0,
        "last_cycle_finished_at": "",
        "last_existing_scan_seconds": 0.0,
        "last_events_total": 0,
        "last_pdf_events": 0,
        "last_xml_events": 0,
        "last_boleto_events": 0,
        "updated_at": "",
    }


def _salvar_status(base_dir: Path, status: dict[str, object], log=print) -> None:
    path = _status_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(_status_padrao())
        payload.update(status or {})
        payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except Exception as e:
        log(f"Falha ao salvar status '{path}': {e}")


def _carregar_status(base_dir: Path, log=print) -> dict[str, object]:
    path = _status_path(base_dir)
    status = _status_padrao()
    if not path.exists():
        return status
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            status.update(raw)
    except Exception as e:
        log(f"Falha ao ler status '{path}': {e}")
    return status


def _carregar_config(base_dir: Path, log=print) -> dict[str, str]:
    cfg = _default_paths(base_dir)
    path = _config_path(base_dir)
    if path.exists():
        try:
            # Some editors/OSes may write a UTF-8 BOM (Byte Order Mark) at the start.
            # Using "utf-8-sig" makes json.loads tolerant to a BOM.
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                for k in cfg:
                    v = raw.get(k)
                    if isinstance(v, str) and v.strip():
                        cfg[k] = v.strip()
        except Exception as e:
            log(f"Falha ao ler configuração '{path}': {e}")

    env_map = {
        "pdf_watch_dir": "PDF_WATCH_DIR",
        "xml_watch_dir": "XML_WATCH_DIR",
        "boleto_watch_dir": "BOLETO_WATCH_DIR",
        "pdf_destino_mva": "PDF_DESTINO_DIR",
        "pdf_destino_horizonte": "PDF_DESTINO_DIR_HORIZONTE",
        "xml_destino_mva": "XML_DESTINO_DIR_MVA",
        "xml_destino_horizonte": "XML_DESTINO_DIR_HORIZONTE",
        "boleto_destino_mva": "BOLETO_DESTINO_DIR_MVA",
        "boleto_destino_horizonte": "BOLETO_DESTINO_DIR_HORIZONTE",
        "email_enabled": "EMAIL_DRAFT_ENABLED",
        "debug_enabled": "DEBUG_LOG_ENABLED",
        "auto_update_enabled": "AUTO_UPDATE_ENABLED",
    }
    for key, env_key in env_map.items():
        val = os.getenv(env_key, "").strip()
        if val:
            cfg[key] = val

    downloads_env = os.getenv("PDF_DOWNLOADS_DIRS", "").strip()
    if downloads_env:
        dirs = _listar_dirs_downloads(downloads_env, base_dir)
        if dirs:
            if not os.getenv("PDF_WATCH_DIR", "").strip():
                cfg["pdf_watch_dir"] = str(dirs[0])
            if not os.getenv("XML_WATCH_DIR", "").strip():
                cfg["xml_watch_dir"] = str(dirs[0])
            if not os.getenv("BOLETO_WATCH_DIR", "").strip():
                cfg["boleto_watch_dir"] = str(dirs[0])
    return cfg


def _salvar_config(base_dir: Path, cfg: dict[str, str]) -> None:
    path = _config_path(base_dir)
    data = {k: (cfg.get(k, "") or "").strip() for k in _default_paths(base_dir)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _log(msg: str, log_path: Path):
    ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    linha = f"[{ts}] {msg}"
    print(linha)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def _carregar_report_state(base_dir: Path, log=print) -> dict[str, str]:
    path = _report_state_path(base_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
        except Exception as e:
            log(f"Falha ao ler estado de relatório '{path}': {e}")
    return {}


def _salvar_report_state(base_dir: Path, state: dict[str, str], log=print) -> None:
    path = _report_state_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"Falha ao salvar estado de relatório '{path}': {e}")


def _carregar_viewer_settings(base_dir: Path, log=print) -> dict[str, bool]:
    path = _viewer_settings_path(base_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {
                    "show_dates": bool(raw.get("show_dates", True)),
                    "show_time": bool(raw.get("show_time", False)),
                    "auto_scroll": bool(raw.get("auto_scroll", False)),
                    "pause_refresh": bool(raw.get("pause_refresh", False)),
                }
        except Exception as e:
            log(f"Falha ao ler configuracoes do visualizador '{path}': {e}")
    return {
        "show_dates": True,
        "show_time": False,
        "auto_scroll": False,
        "pause_refresh": False,
    }


def _salvar_viewer_settings(base_dir: Path, settings: dict[str, bool], log=print) -> None:
    path = _viewer_settings_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"Falha ao salvar configuracoes do visualizador '{path}': {e}")


def _registrar_relatorio(base_dir: Path, nf: str, status: str, motivo: str, log=print) -> None:
    path = _report_path(base_dir)
    ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    linha = f"[{ts}] NF{nf} | {status} | Motivo: {motivo}"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception as e:
        log(f"Falha ao gravar relatório: {e}")


def criar_pasta_data(base_dir: Path) -> Path:
    hoje = datetime.now()
    ano = hoje.strftime("%Y")
    mes_nome = MESES[hoje.month - 1]
    destino = base_dir / ano / mes_nome
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def criar_pasta_data_boleto(base_dir: Path) -> Path:
    hoje = datetime.now()
    destino = base_dir / hoje.strftime("%m-%Y")
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _normalizar_nome_esperado(nome: str) -> str:
    n = nome.strip().lower()
    if not n.endswith(".pdf"):
        n += ".pdf"
    return n


def _eh_pdf_com_nome(nome: str, esperado: str) -> bool:
    return nome.lower() == esperado


def _eh_pdf_valido(nome: str) -> bool:
    n = nome.lower()
    if not n.endswith(".pdf"):
        return False
    return not (n.endswith(".crdownload") or n.endswith(".part"))


def _pdf_parece_boleto(nome: str, texto: str | None = None) -> bool:
    nome_norm = _normalizar_nome_arquivo(nome).upper()
    if "BOLETO" in nome_norm:
        return True
    if re.match(r"^\d{14}-\d+-\d+\.pdf$", nome, re.IGNORECASE):
        return True
    if texto:
        txt = texto.upper()
        if _linha_digitavel_boleto(txt):
            return True
        sinais = (
            "FICHA DE COMPENSACAO",
            "NOSSO NUMERO",
            "BENEFICIARIO",
            "PAGADOR",
            "REFERENTE A NF",
        )
        hits = sum(1 for sinal in sinais if sinal in txt)
        if hits >= 3:
            return True
    return False


def _arquivo_estavel(caminho: Path, intervalo: int = 1, tentativas: int = 3) -> bool:
    try:
        if not caminho.exists():
            return False
        idade_minima = float(os.getenv("PDF_STABLE_AGE_SECONDS", "8"))
        try:
            idade = time.time() - caminho.stat().st_mtime
            if idade >= idade_minima:
                return True
        except Exception:
            pass
        tamanho_anterior = caminho.stat().st_size
        for _ in range(tentativas):
            time.sleep(intervalo)
            if not caminho.exists():
                return False
            tamanho_atual = caminho.stat().st_size
            if tamanho_atual == tamanho_anterior:
                return True
            tamanho_anterior = tamanho_atual
        return False
    except Exception:
        return False


def _extrair_texto_pdf(caminho: Path, log=print) -> str | None:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(caminho))
        partes = []
        for page in reader.pages:
            try:
                partes.append(page.extract_text() or "")
            except Exception:
                partes.append("")
        return "\n".join(partes)
    except Exception as e:
        log(f"Erro ao processar PDF '{caminho.name}': {e}")
        return None


def mover_pdf(origem: Path, destino_dir: Path, log=print, novo_nome: str | None = None) -> Path | None:
    destino = destino_dir / (novo_nome or origem.name)

    if destino.exists():
        log(f"Arquivo já existe no destino, ignorado: {destino}")
        return None

    try:
        shutil.move(str(origem), str(destino))
        log(f"Arquivo movido: {origem.name} -> {destino.name}")
        return destino
    except Exception as e:
        log(f"Erro ao mover {origem.name}: {e}")
        return None


def _expandir_caminho(texto: str) -> Path:
    texto = texto.replace("{USER}", os.getenv("USERNAME", "")).replace("{USERPROFILE}", os.getenv("USERPROFILE", ""))
    return Path(os.path.expandvars(texto))


def _listar_dirs_downloads(valor_env: str, base_dir: Path) -> list[Path]:
    if not valor_env:
        return [Path(os.getenv("USERPROFILE", str(base_dir))) / "Downloads"]
    partes = [p.strip() for p in valor_env.split(";") if p.strip()]
    return [_expandir_caminho(p) for p in partes]


def _normalizar_nome_arquivo(nome: str) -> str:
    n = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r'[<>:"/\\|?*]', "", n).strip()
    return n


def _texto_compacto(valor: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalizar_nome_arquivo(valor).lower())


def _linha_digitavel_boleto(valor: str) -> bool:
    return bool(re.search(r"\b\d{5}\.\d{5}\b", valor) or re.search(r"^\d{3}-\d\b", valor))


def _nome_boleto_parece_invalido(nome: str | None) -> bool:
    if not nome:
        return True
    n = _normalizar_nome_arquivo(nome).strip()
    if not n:
        return True
    u = n.upper()
    if _linha_digitavel_boleto(n):
        return True
    if re.search(r"https?://|AUTOATENDIMENTO|\.BB\.COM\.BR", u):
        return True
    if re.search(r"\b(PAGADOR|BENEFICIARIO|CEDENTE|SACADOR|AVALISTA|NOSSO NUMERO|AGENCIA/CODIGO)\b", u):
        return True
    if re.search(r"\b(ENDERECO|MUNICIPIO UF CEP|NUMERO DO DOCUMENTO|DADOS DO PAGADOR|FICHA DE COMPENSACAO|LOCAL DE PAGAMENTO|COOPERATIVA CONTRATANTE|AUTENTICACAO MECANICA|RECIBO DO PAGADOR|ACOMPANHADO DO RECIBO|RECEBIMENTO|VALIDADE|DATA DO DOCUMENTO|USO DO BANCO|VALOR DOCUMENTO|VENCIMENTO|DESCONTO|ABATIMENTO|OUTRAS DEDUCOES|MORA|MULTA|OUTROS ACRESCIMOS|VALOR COBRADO)\b", u):
        return True
    if re.search(r"\b(NOTA FISCAL|CHAVE DE ACESSO|NFE REF|DANFE|EMISSAO)\b", u):
        return True
    letras = len(re.findall(r"[A-Z]", u))
    digitos = len(re.findall(r"\d", u))
    if letras == 0:
        return True
    if digitos > letras:
        return True
    return False


def _ler_texto_arquivo(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return None


def _ler_texto_bytes(data: bytes) -> str | None:
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return data.decode("latin-1", errors="ignore")
        except Exception:
            return None


def _extrair_nf_do_nome(nome: str) -> str | None:
    base = Path(nome).name
    # Zweb: CNPJ-NOSSO_NUMERO-BANCO.pdf (Não extrair NF daqui)
    m_zweb = re.match(r"^\d{14}-\d+-\d+\.pdf$", base, re.IGNORECASE)
    if m_zweb:
        return None

    m = re.search(r"\bNF[\s\-_]*0*([0-9]{1,9})\b", base, re.IGNORECASE)
    if m:
        return m.group(1).lstrip("0") or m.group(1)
    m = re.search(r"\b([0-9]{4,9})\b", base)
    if m:
        return m.group(1).lstrip("0") or m.group(1)
    return None


def _eh_boleto_valido(nome: str) -> bool:
    n = nome.lower()
    if n.endswith(".crdownload") or n.endswith(".part"):
        return False
    return Path(n).suffix == ".pdf"


def _extrair_info_boleto_pdf(caminho: Path, log=print, texto: str | None = None) -> dict[str, str | None]:
    if texto is None:
        texto = _extrair_texto_pdf(caminho, log=log) or ""
    if not texto.strip():
        return {
            "nf": _extrair_nf_do_nome(caminho.name),
            "pagador": None,
            "nosso_numero": None,
            "beneficiario": None,
            "beneficiario_cnpj": None,
        }

    texto_numeros = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", texto)

    nf = None
    nosso_numero_sicoob = None

    # I check the Sicoob summary line: "NRDOC DM N DD/MM/YYYY NOSSO_NUMERO"
    # N. documento (e.g. 0020776-01) is the NF; the trailing XXXX-D is the Nosso Número
    m_sicoob = re.search(
        r"\b0*([1-9]\d{0,11})(?:-\d{1,2})?\s+(?:DM|DS|NP|DMI|OU)\s+(?:[SN]|[A-Z]{3}|SIM|NAO|N\xc3\x83O)?\s*\d{2}/\d{2}/\d{4}\s+(\d{3,8}-\d{1,2})\b",
        texto_numeros, re.IGNORECASE
    )
    if m_sicoob:
        nf = m_sicoob.group(1).lstrip("0") or m_sicoob.group(1)
        nosso_numero_sicoob = m_sicoob.group(2)

    # I also look for an isolated "XXXX-D" line as Nosso Número fallback (when summary line absent)
    if not nosso_numero_sicoob:
        linhas_texto = [ln.strip() for ln in texto.splitlines()]
        for ln in linhas_texto:
            m_nn_isolado = re.fullmatch(r"(\d{3,8})-(\d{1,2})", ln.strip())
            if m_nn_isolado:
                nosso_numero_sicoob = ln.strip()
                break

    if not nf:
        m_nf = re.search(r"\bNF\s*0*([0-9]{1,12})\b", texto_numeros, re.IGNORECASE)
        nf = m_nf.group(1).lstrip("0") if m_nf else None
    if not nf:
        m_nrdoc = re.search(r"Nr\.\s*do documento.*?\n\s*([0-9]{1,12})\b", texto_numeros, re.IGNORECASE | re.DOTALL)
        if m_nrdoc:
            nf = m_nrdoc.group(1).lstrip("0") or m_nrdoc.group(1)
    if not nf:
        m_ref = re.search(r"REFERENTE\s+A\s+NF\s*0*([0-9]{1,12})\b", texto, re.IGNORECASE)
        if m_ref:
            nf = m_ref.group(1).lstrip("0") or m_ref.group(1)
    if not nf:
        nf = _extrair_nf_do_nome(caminho.name)


    def _extrair_pagador(txt: str) -> str | None:
        linhas = [ln.strip() for ln in txt.splitlines()]
        cnpj_re = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
        texto_mva = os.getenv("BOLETO_TEXT_MATCH_MVA", "MVA").strip()
        texto_horizonte = os.getenv("BOLETO_TEXT_MATCH_HORIZONTE", "HORIZONTE").strip()
        blacklist = {
            "DADOS DO PAGADOR",
            "DADOS DO PAGADOR/AVALISTA",
            "DADOS DO PAGADOR / AVALISTA",
            "DADOS DO SACADO",
            "PAGADOR",
            "PAGADOR/AVALISTA",
            "AVALISTA",
            "SACADO",
            "NOME DO PAGADOR NUMERO DO DOCUMENTO",
            "ENDERECO",
            "ENDEREÇO",
            "MUNICIPIO UF CEP",
            "MUNICÍPIO UF CEP",
            "MENSAGEM PAGADOR",
        }
        labels_pagador = (
            r"nome do pagador",
            r"^pagador$",
            r"pagador/avalista",
            r"dados do pagador",
            r"dados do sacado",
        )

        def _limpar_nome_linha(ln: str) -> str:
            nome = ln.strip()
            if cnpj_re.search(nome):
                partes = [p.strip() for p in cnpj_re.split(nome) if p.strip()]
                nome_escolhido = ""
                for p in partes:
                    if re.search(r'[A-Za-z]', p):
                        nome_escolhido = p
                        break
                nome = nome_escolhido if nome_escolhido else (partes[0] if partes else "")
                nome = nome.lstrip("-: ,;")

            nome = re.sub(r"\s*-\s*CNPJ.*$", "", nome, flags=re.IGNORECASE).strip()
            nome = re.sub(r"\s+CNPJ[:\s].*$", "", nome, flags=re.IGNORECASE).strip()
            nome = re.sub(r"^(CNPJ|CPF)[\s:]*", "", nome, flags=re.IGNORECASE).strip()
            nome = re.sub(rf"\b{re.escape(nf)}\b$", "", nome).strip(" -:;,.") if nf else nome
            return nome

        def _nome_parece_emitente(nome: str) -> bool:
            comp = _texto_compacto(nome)
            if texto_mva and _texto_compacto(texto_mva) in comp:
                return True
            if texto_horizonte and _texto_compacto(texto_horizonte) in comp:
                return True
            return False

        candidato_emitente = None

        for i, ln in enumerate(linhas):
            if not ln:
                continue
            if any(re.search(rx, ln, re.IGNORECASE) for rx in labels_pagador):
                m = re.search(r"PAGADOR\s*[:\-]\s*(.+)$", ln, re.IGNORECASE)
                if m:
                    nome = _limpar_nome_linha(m.group(1))
                    if nome and nome.upper() not in blacklist and not _nome_boleto_parece_invalido(nome):
                        if _nome_parece_emitente(nome):
                            candidato_emitente = candidato_emitente or nome
                        else:
                            return nome
                for j in range(i + 1, min(i + 10, len(linhas))):
                    cand = linhas[j].strip()
                    if not cand:
                        continue
                    if cand.upper() in blacklist:
                        continue
                    if re.search(r"benefici[aá]rio|cedente|sacador|avalista", cand, re.IGNORECASE):
                        break
                    nome = _limpar_nome_linha(cand)
                    if not nome or _nome_boleto_parece_invalido(nome):
                        continue
                    if _nome_parece_emitente(nome):
                        candidato_emitente = candidato_emitente or nome
                        continue
                    return nome

        if nf:
            nf_rx = re.compile(rf"\b{re.escape(nf)}\b")
            for ln in linhas:
                if not ln or not nf_rx.search(ln):
                    continue
                nome = _limpar_nome_linha(re.sub(rf"\b{re.escape(nf)}\b.*$", "", ln).strip())
                if not nome or _nome_boleto_parece_invalido(nome):
                    continue
                if _nome_parece_emitente(nome):
                    candidato_emitente = candidato_emitente or nome
                    continue
                return nome

        for ln in linhas:
            if not ln or not cnpj_re.search(ln):
                continue
            if _linha_digitavel_boleto(ln):
                continue
            if re.search(r"benefici[aá]rio|cedente|sacador|avalista|ag[êe]ncia/c[oó]digo|nosso n[uú]mero", ln, re.IGNORECASE):
                continue
            nome = _limpar_nome_linha(ln)
            if nome and nome.upper() not in blacklist and not _nome_boleto_parece_invalido(nome):
                if _nome_parece_emitente(nome):
                    candidato_emitente = candidato_emitente or nome
                    continue
                return nome

        if candidato_emitente:
            return candidato_emitente
        return None

    def _extrair_beneficiario(txt: str) -> str | None:
        linhas = [ln.strip() for ln in txt.splitlines()]
        texto_mva = os.getenv("BOLETO_TEXT_MATCH_MVA", "MVA").strip()
        texto_horizonte = os.getenv("BOLETO_TEXT_MATCH_HORIZONTE", "HORIZONTE").strip()

        def _contem_termo_esperado(ln: str, termo: str) -> bool:
            if not termo:
                return False
            return _texto_compacto(termo) in _texto_compacto(ln)

        for ln in linhas:
            if not ln:
                continue
            if _contem_termo_esperado(ln, texto_mva):
                return ln
            if _contem_termo_esperado(ln, texto_horizonte):
                return ln

        blacklist = {
            "LOCAL DE PAGAMENTO",
            "DATA DO DOCUMENTO",
            "USO DO BANCO",
            "INSTRUCOES (TEXTO DE RESPONSABILIDADE DO BENEFICIARIO)",
            "INSTRUÇÕES (TEXTO DE RESPONSABILIDADE DO BENEFICIÁRIO)",
            "PAGADOR",
            "BENEFICIARIO FINAL",
            "BENEFICI?RIO FINAL",
            "FICHA DE COMPENSACAO",
            "FICHA DE COMPENSAÇÃO",
            "VENCIMENTO",
            "NOSSO NUMERO",
            "NOSSO NÚMERO",
            "VALOR DOCUMENTO",
        }

        def _nome_beneficiario_valido(ln: str) -> bool:
            if not ln:
                return False
            if ln.upper() in blacklist:
                return False
            if re.search(r"benefici[aá]rio", ln, re.IGNORECASE):
                return False
            return not _nome_boleto_parece_invalido(ln)

        for i, ln in enumerate(linhas):
            if re.search(r"nome do benefici[aá]rio|\bbenefici[aá]rio\b", ln, re.IGNORECASE):
                for j in range(i + 1, min(i + 6, len(linhas))):
                    v = linhas[j].strip()
                    if not v:
                        continue
                    if not _nome_beneficiario_valido(v):
                        continue
                    return v
        return None

    pagador = _extrair_pagador(texto)
    if pagador:
        pagador = pagador.split(" - CNPJ", 1)[0].strip()
        pagador = _normalizar_nome_arquivo(pagador)
    if not pagador:
        linhas = [ln.strip() for ln in texto.splitlines()]
        cnpj_re = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
        for ln in linhas:
            if not ln:
                continue
            if _linha_digitavel_boleto(ln):
                continue
            if cnpj_re.search(ln):
                if re.search(r"benefici[aá]rio|cedente|sacador|avalista|ag[êe]ncia/c[oó]digo|nosso n[uú]mero", ln, re.IGNORECASE):
                    continue
                nome = cnpj_re.split(ln)[0].strip()
                if nome and not _nome_boleto_parece_invalido(nome):
                    pagador = _normalizar_nome_arquivo(nome)
                    break

    def _parece_cep_truncado(valor: str | None, texto_ref: str) -> bool:
        if not valor:
            return False
        valor = valor.strip()
        if not re.fullmatch(r"\d{5}-\d{2}", valor):
            return False
        prefixo = re.sub(r"\D", "", valor)
        for cep in re.findall(r"\d{5}-\d{3}", texto_ref):
            if re.sub(r"\D", "", cep).startswith(prefixo):
                return True
        return False

    def _linha_tem_nosso_numero(linha: str) -> bool:
        return "NOSSO NUMERO" in _normalizar_nome_arquivo(linha).upper()

    def _nosso_valido(valor: str | None, allow_leading_zeros: bool = False, texto_ref: str = "") -> bool:
        if not valor:
            return False
        valor = valor.strip()
        v = re.sub(r"\D", "", valor)
        if not v:
            return False
        if _parece_cep_truncado(valor, texto_ref):
            return False
        if v.startswith("0800") and len(v) <= 11:
            return False
        if not allow_leading_zeros and v.startswith("000"):
            return False
        if re.fullmatch(r"\d{5}-\d{3}", valor):
            return False
        if "-" in valor:
            return len(v) >= 5
        return len(v) >= 5

    def _escolher_melhor_nosso(candidatos: list[str], allow_leading_zeros: bool = False, texto_ref: str = "") -> str | None:
        validos = []
        for cand in candidatos:
            cand = cand.strip()
            if not _nosso_valido(cand, allow_leading_zeros=allow_leading_zeros, texto_ref=texto_ref):
                continue
            validos.append(cand)
        if not validos:
            return None
        validos.sort(key=lambda c: (1 if "-" in c else 0, len(re.sub(r"\D", "", c))), reverse=True)
        return validos[0]

    def _extrair_nosso_linha_documento(nf_ref: str | None, texto_ref: str) -> str | None:
        if not nf_ref:
            return None
        linhas_ref = [ln.strip() for ln in texto_ref.splitlines()]
        for ln in linhas_ref:
            if not ln or nf_ref not in ln:
                continue
            ln_norm = f" {_normalizar_nome_arquivo(ln).upper()} "
            if not any(marker in ln_norm for marker in (" DM ", " DS ", " NP ", " DMI ")):
                continue
            cands = re.findall(r"\d{4,20}(?:-\d{1,2})?", ln)
            cands = [c for c in cands if c != nf_ref and not re.fullmatch(r"20\d{2}", c)]
            nosso_doc = _escolher_melhor_nosso(cands, allow_leading_zeros=True, texto_ref=texto_ref)
            if nosso_doc:
                return nosso_doc
        return None

    nosso_numero = nosso_numero_sicoob
    if not nosso_numero:
        m_zweb_nome = re.match(r"^\d{14}-(\d+)-\d+\.pdf$", caminho.name, re.IGNORECASE)
        if m_zweb_nome:
            blt_digits = m_zweb_nome.group(1)
            if len(blt_digits) >= 2:
                nosso_numero = f"{blt_digits[:-1]}-{blt_digits[-1]}"
            else:
                nosso_numero = blt_digits

    if not nosso_numero:
        m_cx = re.findall(r"\d{11,20}-\d{1,2}", texto_numeros)
        nosso_numero = _escolher_melhor_nosso(m_cx, texto_ref=texto_numeros)
    if not nosso_numero:
        nosso_numero = _extrair_nosso_linha_documento(nf, texto_numeros)
    if not nosso_numero:
        texto_nosso_norm = _normalizar_nome_arquivo(texto_numeros)
        m_nosso = re.search(r"Nosso\s*numero.{0,180}?(\d{4,20}-\d{1,2}|\d{5,20})", texto_nosso_norm, re.IGNORECASE)
        if m_nosso and _nosso_valido(m_nosso.group(1), allow_leading_zeros=True, texto_ref=texto_numeros):
            nosso_numero = m_nosso.group(1)
    if not nosso_numero:
        linhas_num = [ln.strip() for ln in texto_numeros.splitlines()]
        for i, ln in enumerate(linhas_num):
            if not _linha_tem_nosso_numero(ln):
                continue
            janela = " ".join(linhas_num[i:i+8])
            cands = re.findall(r"\d{4,20}-\d{1,2}|\d{5,20}", janela)
            nosso_numero = _escolher_melhor_nosso(cands, allow_leading_zeros=True, texto_ref=texto_numeros)
            if nosso_numero:
                break
    if not nosso_numero:
        cands = re.findall(r"\d{4,20}-\d{1,2}", texto_numeros)
        nosso_numero = _escolher_melhor_nosso(cands, texto_ref=texto_numeros)


    beneficiario = _extrair_beneficiario(texto)
    if beneficiario:
        beneficiario = _normalizar_nome_arquivo(beneficiario)
        beneficiario = re.sub(r"\s+\d{2}/\d{2}/\d{4}.*$", "", beneficiario)
        beneficiario = re.sub(r"\s+\d{8}.*$", "", beneficiario)
        beneficiario = re.sub(r"\s+R\$\s*[\d\.,]+.*$", "", beneficiario)
        beneficiario = re.sub(r"\s+R\$\s*$", "", beneficiario)

    m_benef_cnpj = re.search(
        r"CPF/CNPJ Benefici[aá]rio.*?\n.*?([0-9]{2}\.?[0-9]{3}\.?[0-9]{3}/?[0-9]{4}-?[0-9]{2})",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    beneficiario_cnpj = None
    if m_benef_cnpj:
        beneficiario_cnpj = re.sub(r"\D", "", m_benef_cnpj.group(1))

    return {
        "nf": nf,
        "pagador": pagador,
        "nosso_numero": nosso_numero,
        "beneficiario": beneficiario,
        "beneficiario_cnpj": beneficiario_cnpj,
    }


def _compactar_nosso_numero_para_nome(valor: str) -> str:
    final_nosso = (valor or "").strip()
    if not final_nosso:
        return final_nosso
    if "-" in final_nosso:
        base, digito = final_nosso.rsplit("-", 1)
        base_digits = re.sub(r"\D", "", base)
        digito_digits = re.sub(r"\D", "", digito)
        if base_digits and digito_digits:
            if len(base_digits) <= 5:
                return f"{base_digits}-{digito_digits}"
            return f"{base_digits[-4:]}-{digito_digits}"
        return final_nosso

    digitos_nosso = re.sub(r"\D", "", final_nosso)
    digitos_significativos = digitos_nosso.lstrip("0") or digitos_nosso
    m_sufixo_zeros = re.search(r"0{3,}(\d{5,6})$", digitos_nosso)
    if m_sufixo_zeros:
        return m_sufixo_zeros.group(1).lstrip("0") or m_sufixo_zeros.group(1)
    if len(digitos_significativos) <= 6:
        return digitos_significativos
    return digitos_significativos[-4:] if len(digitos_significativos) >= 4 else digitos_significativos


def _nomear_boleto(info: dict[str, str | None], fallback_nome: str) -> str:
    nf = (info.get("nf") or "").strip()
    pagador = (info.get("pagador") or "").strip()
    nosso_num = (info.get("nosso_numero") or "").strip()
    if not nf or not pagador:
        return fallback_nome
    pagador_norm = _normalizar_nome_arquivo(pagador).upper()
    palavras = re.findall(r"[A-Z0-9]+", pagador_norm)
    pagador_curto = " ".join(palavras[:2]).strip() if palavras else pagador_norm
    final_nosso = nosso_num
    if final_nosso:
        final_nosso = _compactar_nosso_numero_para_nome(final_nosso)
    sufixo = f" BLT {final_nosso}" if final_nosso else ""
    return f"BOLETO NF{nf} {pagador_curto}{sufixo}.pdf"


def _nome_boleto_tem_numero(nome: str) -> bool:
    nome_norm = _normalizar_nome_arquivo(nome).upper()
    return bool(re.search(r"\bBLT\s+\d{3,}(?:-\d{1,2})?\b", nome_norm))


def _nomear_boleto_pendente(info: dict[str, str | None], fallback_nome: str) -> str:
    if _nome_boleto_tem_numero(fallback_nome):
        return Path(fallback_nome).name
    info_pendente = dict(info)
    info_pendente["nosso_numero"] = None
    return _nomear_boleto(info_pendente, fallback_nome)


def _encaminhar_boleto_pendente(origem: Path, workspace_dir: Path, info: dict[str, str | None], log=print) -> Path | None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    novo_nome = _nomear_boleto_pendente(info, origem.name)
    try:
        if origem.parent.resolve() == workspace_dir.resolve() and origem.name == novo_nome:
            log(f"Boleto pendente mantido no workspace para revisão manual: {origem.name}")
            return origem
    except Exception:
        pass
    log(f"Boleto pendente sem número identificado; enviando para o workspace: {origem.name} -> {novo_nome}")
    return mover_pdf(origem, workspace_dir, log=log, novo_nome=novo_nome)


def _extrair_nf_xml_texto(texto: str) -> str | None:
    m = re.search(r"<nNF>\s*0*([0-9]{1,12})\s*</nNF>", texto, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lstrip("0") or m.group(1)


def _extrair_dados_nf(texto: str) -> tuple[str | None, str | None]:
    nf_num = None
    m = re.search(r"N[ºo]\.?\s*([0-9\.\-]+)", texto, re.IGNORECASE)
    if m:
        nf_num = re.sub(r"\D", "", m.group(1))
        nf_num = nf_num.lstrip("0") or nf_num

    razao = None
    m = re.search(r"DESTINAT[ÁA]RIO:\s*(.+)", texto, re.IGNORECASE)
    if m:
        razao = m.group(1).split(" - ", 1)[0].strip()
    else:
        linhas = [l.strip() for l in texto.splitlines()]
        for i, linha in enumerate(linhas):
            if re.match(r"^NOME\s*/\s*RAZ", linha, re.IGNORECASE):
                for j in range(i + 1, min(i + 4, len(linhas))):
                    if linhas[j]:
                        razao = linhas[j]
                        break
                if razao:
                    break
    if razao:
        razao = _normalizar_nome_arquivo(razao)
    return nf_num, razao


def _montar_nome_pdf(texto_pdf: str, log=print) -> str | None:
    nf_num, razao = _extrair_dados_nf(texto_pdf)
    if not nf_num or not razao:
        log("Não foi possível extrair NF ou razão social para renomear.")
        return None
    return f"PDF NF{nf_num} {razao}.pdf"


def _carregar_diretorios_xml(cfg: dict[str, str]) -> dict[str, Path]:
    return {
        "HORIZONTE": Path(cfg["xml_destino_horizonte"]),
        "MVA": Path(cfg["xml_destino_mva"]),
    }


def _extrair_cnpj_emitente(xml_texto: str) -> str | None:
    m_emit = re.search(r"<emit>.*?</emit>", xml_texto, re.IGNORECASE | re.DOTALL)
    if not m_emit:
        return None
    m_cnpj = re.search(r"<CNPJ>\s*([0-9]{14})\s*</CNPJ>", m_emit.group(0), re.IGNORECASE)
    if not m_cnpj:
        return None
    return m_cnpj.group(1)


def _destino_xml_por_cnpj(xml_texto: str, destinos_xml: dict[str, Path], cnpj_mva: str, cnpj_horizonte: str) -> Path | None:
    cnpj_emit = _extrair_cnpj_emitente(xml_texto) or ""
    if cnpj_mva and cnpj_emit == cnpj_mva:
        return destinos_xml.get("MVA")
    if cnpj_horizonte and cnpj_emit == cnpj_horizonte:
        return destinos_xml.get("HORIZONTE")
    return None


def _salvar_xml_bytes(destino_dir: Path, nome_arquivo: str, conteudo: bytes, log=print) -> Path | None:
    base_nome = _normalizar_nome_arquivo(Path(nome_arquivo).name) or "arquivo.xml"
    if not base_nome.lower().endswith(".xml"):
        base_nome += ".xml"
    destino = destino_dir / base_nome
    if destino.exists():
        stem = destino.stem
        ext = destino.suffix
        i = 1
        while True:
            candidato = destino_dir / f"{stem}_{i}{ext}"
            if not candidato.exists():
                destino = candidato
                break
            i += 1
    try:
        destino.write_bytes(conteudo)
        log(f"XML extraido e movido: {base_nome} -> {destino.name}")
        return destino
    except Exception as e:
        log(f"Erro ao salvar XML extraido '{base_nome}': {e}")
        return None


def _eh_pacote_nfes(nome: str) -> bool:
    return bool(NFES_PACOTE_RE.search(nome))


def _state_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    state_dir = appdata / APP_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "drafted_nfs.txt"


def _carregar_nfs_rascunho(base_dir: Path, log=print) -> set[str]:
    path = _state_path(base_dir)
    nfs = set()
    if path.exists():
        try:
            for linha in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                nf = linha.strip()
                if nf:
                    nfs.add(nf)
            return nfs
        except Exception as e:
            log(f"Falha ao ler estado de rascunhos '{path}': {e}")

    # Compatibilidade com versões antigas que usavam JSON.
    path_json = path.with_suffix(".json")
    if not path_json.exists():
        return nfs
    try:
        data = json.loads(path_json.read_text(encoding="utf-8"))
        if isinstance(data, list):
            nfs = {str(x).strip() for x in data if str(x).strip()}
    except Exception as e:
        log(f"Falha ao ler estado de rascunhos '{path_json}': {e}")
    if nfs:
        _salvar_nfs_rascunho(base_dir, nfs, log=log)
    return nfs


def _salvar_nfs_rascunho(base_dir: Path, nfs: set[str], log=print) -> None:
    path = _state_path(base_dir)
    try:
        conteudo = "\n".join(sorted(nfs))
        if conteudo:
            conteudo += "\n"
        path.write_text(conteudo, encoding="utf-8")
    except Exception as e:
        log(f"Falha ao salvar estado de rascunhos '{path}': {e}")


def _sent_state_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    state_dir = appdata / APP_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "sent_nfs.txt"


def _carregar_nfs_enviadas(base_dir: Path, log=print) -> set[str]:
    path = _sent_state_path(base_dir)
    if not path.exists():
        return set()
    try:
        return {l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()}
    except Exception as e:
        log(f"Falha ao ler estado de enviados '{path}': {e}")
        return set()


def _salvar_nfs_enviadas(base_dir: Path, nfs: set[str], log=print) -> None:
    path = _sent_state_path(base_dir)
    try:
        conteudo = "\n".join(sorted(nfs))
        if conteudo:
            conteudo += "\n"
        path.write_text(conteudo, encoding="utf-8")
    except Exception as e:
        log(f"Falha ao salvar estado de enviados '{path}': {e}")


def _template_path(base_dir: Path) -> Path:
    local = base_dir / "message_template.txt"
    if local.exists():
        return local
    bundled = _bundle_dir() / "message_template.txt"
    return bundled if bundled.exists() else local


# Sessão Criador de Email
def _montar_corpo_email(base_dir: Path, nf: str) -> str:
    path = _template_path(base_dir)
    if path.exists():
        txt = path.read_text(encoding="utf-8", errors="ignore")
    else:
        txt = "Boa tarde!!!\n\nSegue em anexo XML PDF NF{NF} + BOLETO\n\n***Favor confirmar e-mail***\nAtt"
    txt = re.sub(r"\{NF\}", nf, txt, flags=re.IGNORECASE)
    if f"NF{nf}" not in txt:
        txt += f"\n\nNF{nf}"
    return txt


def _localizar_credentials(base_dir: Path) -> Path | None:
    p = base_dir / "credentials.json"
    if p.exists():
        return p
    p_bundle = _bundle_dir() / "credentials.json"
    if p_bundle.exists():
        return p_bundle
    candidatos = sorted(base_dir.glob("client_secret_*.json"))
    if candidatos:
        return candidatos[0]
    candidatos_bundle = sorted(_bundle_dir().glob("client_secret_*.json"))
    return candidatos_bundle[0] if candidatos_bundle else None


def _gmail_service(base_dir: Path, log=print):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as e:
        log(f"Dependencias Google nao encontradas: {e}")
        return None

    creds_file = _localizar_credentials(base_dir)
    if not creds_file:
        log("Credenciais OAuth nao encontradas (credentials.json).")
        return None
    token_file = base_dir / "token.json"
    scopes = [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    try:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        log(f"Falha ao criar cliente Gmail: {e}")
        return None


def _criar_rascunho_gmail(service, assunto: str, corpo: str, anexos: list[Path], log=print) -> str | None:
    msg = EmailMessage()
    destinatarios = os.getenv("GMAIL_DRAFT_TO", "").strip()
    if destinatarios:
        msg["To"] = destinatarios
    cc = os.getenv("GMAIL_DRAFT_CC", "").strip()
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = assunto
    msg.set_content(corpo)
    for anexo in anexos:
        if not anexo or not anexo.exists():
            continue
        mime, _ = mimetypes.guess_type(str(anexo))
        if mime:
            maintype, subtype = mime.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        try:
            msg.add_attachment(anexo.read_bytes(), maintype=maintype, subtype=subtype, filename=anexo.name)
        except Exception as e:
            log(f"Falha ao anexar '{anexo.name}': {e}")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    try:
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return draft.get("id")
    except Exception as e:
        log(f"Falha ao criar rascunho Gmail: {e}")
        return None


def _nf_enviada_gmail(service, nf: str, log=print) -> bool:
    try:
        q = f'in:sent subject:"XML PDF NF{nf} + BOLETO"'
        resp = service.users().messages().list(userId="me", q=q, maxResults=1).execute()
        return bool(resp.get("messages"))
    except Exception as e:
        log(f"Falha ao consultar enviados no Gmail para NF{nf}: {e}")
        return False


def _cliente_por_bucket(bucket: dict[str, Path]) -> str:
    boleto = bucket.get("boleto")
    if boleto and boleto.exists():
        info = _extrair_info_boleto_pdf(boleto, log=lambda *_: None)
        pagador = (info.get("pagador") or "").strip()
        if pagador:
            pagador_norm = _normalizar_nome_arquivo(pagador).upper()
            palavras = re.findall(r"[A-Z0-9]+", pagador_norm)
            if palavras:
                return " ".join(palavras[:3])
    pdf = bucket.get("pdf")
    if pdf:
        m = re.search(r"NF\s*\d+\s+(.+?)\.pdf$", pdf.name, re.IGNORECASE)
        if m:
            texto = _normalizar_nome_arquivo(m.group(1)).upper()
            palavras = re.findall(r"[A-Z0-9]+", texto)
            if palavras:
                return " ".join(palavras[:3])
    return "CLIENTE NAO IDENTIFICADO"


def _processar_zip_nfes(zip_path: Path, destinos_xml: dict[str, Path], cnpj_mva: str, cnpj_horizonte: str, cache: dict, log=print) -> list[dict]:
    movidos_info = []
    try:
        st = zip_path.stat()
        zip_key = f"ZIPPKG|{zip_path}|{st.st_size}|{int(st.st_mtime)}"
    except Exception:
        zip_key = f"ZIPPKG|{zip_path}"
    if zip_key in cache:
        return movidos_info
    if not _arquivo_estavel(zip_path, intervalo=2):
        return movidos_info
    movidos = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                nome_interno = info.filename or ""
                if not nome_interno.lower().endswith(".xml"):
                    continue
                raw = zf.read(info)
                texto = _ler_texto_bytes(raw)
                if not texto:
                    continue
                destino_base = _destino_xml_por_cnpj(texto, destinos_xml, cnpj_mva, cnpj_horizonte)
                if not destino_base:
                    continue
                nf = _extrair_nf_xml_texto(texto) or _extrair_nf_do_nome(nome_interno)
                destino_dir = criar_pasta_data(destino_base)
                salvo = _salvar_xml_bytes(destino_dir, Path(nome_interno).name, raw, log=log)
                if salvo:
                    movidos += 1
                    movidos_info.append({"tipo": "xml", "path": salvo, "nf": nf})
    except Exception as e:
        log(f"Erro processando ZIP de XML '{zip_path.name}': {e}")
        cache[zip_key] = time.time()
        return movidos_info
    if movidos:
        log(f"Pacote ZIP processado: {zip_path.name} ({movidos} XML)")
    cache[zip_key] = time.time()
    return movidos_info


def _processar_pasta_nfes(pasta: Path, destinos_xml: dict[str, Path], cnpj_mva: str, cnpj_horizonte: str, cache: dict, log=print) -> list[dict]:
    movidos_info = []
    try:
        xmls = [p for p in pasta.rglob("*.xml") if p.is_file()]
        st = pasta.stat()
        dir_key = f"DIRPKG|{pasta}|{int(st.st_mtime)}|{len(xmls)}"
    except Exception:
        dir_key = f"DIRPKG|{pasta}"
        xmls = []
    if dir_key in cache:
        return movidos_info
    movidos = 0
    for xml_path in xmls:
        try:
            stat = xml_path.stat()
            xml_key = f"{xml_path}|{stat.st_size}|{int(stat.st_mtime)}"
        except Exception:
            xml_key = str(xml_path)
        if xml_key in cache:
            continue
        if not _arquivo_estavel(xml_path, intervalo=1):
            continue
        texto = _ler_texto_arquivo(xml_path)
        if not texto:
            cache[xml_key] = time.time()
            continue
        destino_base = _destino_xml_por_cnpj(texto, destinos_xml, cnpj_mva, cnpj_horizonte)
        if not destino_base:
            cache[xml_key] = time.time()
            continue
        nf = _extrair_nf_xml_texto(texto) or _extrair_nf_do_nome(xml_path.name)
        destino_dir = criar_pasta_data(destino_base)
        log(f"XML movendo para: {destino_dir}")
        movido = mover_pdf(xml_path, destino_dir, log=log)
        if movido:
            movidos += 1
            movidos_info.append({"tipo": "xml", "path": movido, "nf": nf})
        cache[xml_key] = time.time()
    if movidos:
        log(f"Pasta de XML processada: {pasta.name} ({movidos} XML)")
    cache[dir_key] = time.time()
    return movidos_info


def processar_xmls(downloads_dir: Path, destinos_xml: dict[str, Path], cnpj_mva: str, cnpj_horizonte: str, cache: dict, log=print, debug_log=None) -> list[dict]:
    movidos_info = []
    if not downloads_dir.exists():
        if debug_log:
            debug_log(f"[XML] Diretório não encontrado: {downloads_dir}")
        return movidos_info
    try:
        itens = list(downloads_dir.iterdir())
    except Exception as e:
        log(f"Erro lendo diretório '{downloads_dir}': {e}")
        return movidos_info
    if debug_log:
        debug_log(f"[XML] Total itens na pasta: {len(itens)}")

    for item in itens:
        nome_item = item.name
        if item.is_dir() and _eh_pacote_nfes(nome_item):
            if debug_log:
                debug_log(f"[XML] Pacote de pasta detectado: {item}")
            movidos_info.extend(_processar_pasta_nfes(item, destinos_xml, cnpj_mva, cnpj_horizonte, cache, log=log))
        elif item.is_file() and nome_item.lower().endswith(".zip") and _eh_pacote_nfes(nome_item):
            if debug_log:
                debug_log(f"[XML] Pacote ZIP detectado: {item}")
            movidos_info.extend(_processar_zip_nfes(item, destinos_xml, cnpj_mva, cnpj_horizonte, cache, log=log))

    candidatos = [item.name for item in itens if item.is_file() and item.name.lower().endswith(".xml")]
    if debug_log:
        debug_log(f"[XML] Candidatos XML: {len(candidatos)}")
    agora = time.time()
    for nome in candidatos:
        caminho = downloads_dir / nome
        try:
            stat = caminho.stat()
            cache_key = f"{caminho}|{stat.st_size}|{int(stat.st_mtime)}"
        except Exception:
            cache_key = str(caminho)
        if cache_key in cache:
            if debug_log:
                debug_log(f"[XML] Ignorado (cache): {caminho}")
            continue
        if not _arquivo_estavel(caminho, intervalo=2):
            if debug_log:
                debug_log(f"[XML] Ignorado (arquivo instavel): {caminho}")
            continue
        texto = _ler_texto_arquivo(caminho)
        if not texto:
            if debug_log:
                debug_log(f"[XML] Ignorado (sem texto): {caminho}")
            cache[cache_key] = agora
            continue
        destino_base = _destino_xml_por_cnpj(texto, destinos_xml, cnpj_mva, cnpj_horizonte)
        if not destino_base:
            if debug_log:
                debug_log(f"[XML] Ignorado (CNPJ nao reconhecido): {caminho}")
            cache[cache_key] = agora
            continue
        nf = _extrair_nf_xml_texto(texto) or _extrair_nf_do_nome(nome)
        destino_dir = criar_pasta_data(destino_base)
        log(f"XML movendo para: {destino_dir}")
        movido = mover_pdf(caminho, destino_dir, log=log)
        if movido:
            movidos_info.append({"tipo": "xml", "path": movido, "nf": nf})
        cache[cache_key] = agora
    return movidos_info


def processar_pdfs(downloads_dir: Path, destino_mva: Path, destino_horizonte: Path, nome_arquivo: str, padrao_regex: str, texto_mva: str, texto_horizonte: str, cache: dict, log=print, debug_log=None) -> list[dict]:
    movidos_info = []
    if not downloads_dir.exists():
        log(f"Diretório não encontrado: {downloads_dir}")
        return movidos_info
    try:
        nomes = os.listdir(downloads_dir)
    except Exception as e:
        log(f"Erro lendo diretório '{downloads_dir}': {e}")
        return movidos_info
    if debug_log:
        debug_log(f"[PDF] Total arquivos na pasta: {len(nomes)}")

    if nome_arquivo:
        esperado = _normalizar_nome_esperado(nome_arquivo)
        candidatos = [n for n in nomes if _eh_pdf_com_nome(n, esperado)]
    elif padrao_regex:
        try:
            rx = re.compile(padrao_regex, re.IGNORECASE)
        except re.error as e:
            log(f"Regex invalida em PDF_PATTERN: {e}")
            return movidos_info
        candidatos = [n for n in nomes if _eh_pdf_valido(n) and rx.search(n)]
    else:
        candidatos = [n for n in nomes if _eh_pdf_valido(n)]
    if debug_log:
        debug_log(f"[PDF] Candidatos PDF: {len(candidatos)}")

    agora = time.time()
    for nome in candidatos:
        caminho = downloads_dir / nome
        try:
            stat = caminho.stat()
            cache_key = f"{caminho}|{stat.st_size}|{int(stat.st_mtime)}"
        except Exception:
            cache_key = str(caminho)
        if cache_key in cache:
            if debug_log:
                debug_log(f"[PDF] Ignorado (cache): {caminho}")
            continue
        if not _arquivo_estavel(caminho, intervalo=2):
            if debug_log:
                debug_log(f"[PDF] Ignorado (arquivo instavel): {caminho}")
            continue
        texto = _extrair_texto_pdf(caminho, log=log)
        if _pdf_parece_boleto(nome, texto):
            if debug_log:
                debug_log(f"[PDF] Ignorado (identificado como boleto): {caminho}")
            cache[cache_key] = agora
            continue
        if (texto_mva or texto_horizonte) and not texto:
            if debug_log:
                debug_log(f"[PDF] Ignorado (sem texto PDF): {caminho}")
            cache[cache_key] = agora
            continue
        if texto_mva and texto and texto_mva.lower() in texto.lower():
            destino_dir = criar_pasta_data(destino_mva)
            novo_nome = _montar_nome_pdf(texto, log=log)
            if not novo_nome:
                if debug_log:
                    debug_log(f"[PDF] Ignorado (nao extraiu nome NF): {caminho}")
                cache[cache_key] = agora
                continue
            log(f"PDF movendo para: {destino_dir} ({novo_nome})")
            movido = mover_pdf(caminho, destino_dir, log=log, novo_nome=novo_nome)
            if movido:
                movidos_info.append({"tipo": "pdf", "path": movido, "nf": _extrair_nf_do_nome(movido.name)})
            cache[cache_key] = agora
            continue
        if texto_horizonte and texto and texto_horizonte.lower() in texto.lower():
            destino_dir = criar_pasta_data(destino_horizonte)
            novo_nome = _montar_nome_pdf(texto, log=log)
            if not novo_nome:
                if debug_log:
                    debug_log(f"[PDF] Ignorado (nao extraiu nome NF): {caminho}")
                cache[cache_key] = agora
                continue
            log(f"PDF movendo para: {destino_dir} ({novo_nome})")
            movido = mover_pdf(caminho, destino_dir, log=log, novo_nome=novo_nome)
            if movido:
                movidos_info.append({"tipo": "pdf", "path": movido, "nf": _extrair_nf_do_nome(movido.name)})
            cache[cache_key] = agora
            continue
        cache[cache_key] = agora
        if texto_mva or texto_horizonte:
            log(f"Ignorado (texto nao encontrado): {nome}")
            if debug_log:
                debug_log(f"[PDF] Ignorado (texto MVA/HORIZONTE nao encontrado): {caminho}")
            continue
        destino_dir = criar_pasta_data(destino_mva)
        log(f"PDF movendo para: {destino_dir}")
        movido = mover_pdf(caminho, destino_dir, log=log)
        if movido:
            movidos_info.append({"tipo": "pdf", "path": movido, "nf": _extrair_nf_do_nome(movido.name)})
        cache[cache_key] = agora
    return movidos_info


def processar_boletos(
    downloads_dir: Path,
    destino_mva: Path,
    destino_horizonte: Path,
    cnpj_mva: str,
    cnpj_horizonte: str,
    cache: dict,
    workspace_dir: Path | None = None,
    log=print,
    debug_log=None,
) -> list[dict]:
    movidos_info = []
    if not downloads_dir.exists():
        log(f"Diretório não encontrado: {downloads_dir}")
        return movidos_info
    try:
        nomes = os.listdir(downloads_dir)
    except Exception as e:
        log(f"Erro lendo diretório '{downloads_dir}': {e}")
        return movidos_info

    candidatos = [n for n in nomes if _eh_boleto_valido(n)]
    if debug_log:
        debug_log(f"[BOLETO] Total arquivos na pasta: {len(nomes)}")
        debug_log(f"[BOLETO] Candidatos boleto: {len(candidatos)}")
    agora = time.time()
    texto_mva = os.getenv("BOLETO_TEXT_MATCH_MVA", "MVA").strip().lower()
    texto_horizonte = os.getenv("BOLETO_TEXT_MATCH_HORIZONTE", "HORIZONTE").strip().lower()

    for nome in candidatos:
        caminho = downloads_dir / nome
        if not caminho.is_file():
            if debug_log:
                debug_log(f"[BOLETO] Ignorado (nao arquivo): {caminho}")
            continue
        try:
            stat = caminho.stat()
            cache_key = f"BOLETO|{caminho}|{stat.st_size}|{int(stat.st_mtime)}"
        except Exception:
            cache_key = f"BOLETO|{caminho}"
        if cache_key in cache:
            if debug_log:
                debug_log(f"[BOLETO] Ignorado (cache): {caminho}")
            continue
        if not _arquivo_estavel(caminho, intervalo=2):
            if debug_log:
                debug_log(f"[BOLETO] Ignorado (arquivo instavel): {caminho}")
            continue

        texto = _extrair_texto_pdf(caminho, log=log) or ""
        if not _pdf_parece_boleto(nome, texto):
            if debug_log:
                debug_log(f"[BOLETO] Ignorado (nao parece boleto): {caminho}")
            cache[cache_key] = agora
            continue

        info_boleto = _extrair_info_boleto_pdf(caminho, log=log, texto=texto)
        pagador = (info_boleto.get("pagador") or "").strip()
        beneficiario = (info_boleto.get("beneficiario") or "").strip()
        erros_extracao = []
        if not pagador:
            erros_extracao.append("pagador_vazio")
        elif _nome_boleto_parece_invalido(pagador):
            erros_extracao.append(f"pagador_invalido={pagador}")
        if not beneficiario:
            erros_extracao.append("beneficiario_vazio")
        elif _nome_boleto_parece_invalido(beneficiario):
            erros_extracao.append(f"beneficiario_invalido={beneficiario}")
        if pagador and beneficiario and _texto_compacto(pagador) == _texto_compacto(beneficiario):
            erros_extracao.append("pagador_igual_beneficiario")
        if erros_extracao:
            log(f"Boleto ignorado por falha de extração ({caminho.name}): {'; '.join(erros_extracao)}")
            if debug_log:
                debug_log(f"[BOLETO] Ignorado (falha extracao): {caminho} | {'; '.join(erros_extracao)}")
            cache[cache_key] = agora
            continue
        benef = (info_boleto.get("beneficiario") or "").lower()
        benef_cnpj = (info_boleto.get("beneficiario_cnpj") or "").strip()
        destino_dir = criar_pasta_data_boleto(destino_mva)
        empresa = "MVA"
        if cnpj_horizonte and benef_cnpj and benef_cnpj == cnpj_horizonte:
            destino_dir = criar_pasta_data_boleto(destino_horizonte)
            empresa = "HORIZONTE"
        elif cnpj_mva and benef_cnpj and benef_cnpj == cnpj_mva:
            destino_dir = criar_pasta_data_boleto(destino_mva)
            empresa = "MVA"
        elif texto_horizonte and texto_horizonte in benef:
            destino_dir = criar_pasta_data_boleto(destino_horizonte)
            empresa = "HORIZONTE"
        elif texto_mva and texto_mva in benef:
            destino_dir = criar_pasta_data_boleto(destino_mva)
            empresa = "MVA"
        if not (info_boleto.get("nosso_numero") or "").strip():
            pendente_dir = workspace_dir or downloads_dir
            movido = _encaminhar_boleto_pendente(caminho, pendente_dir, info_boleto, log=log)
            if debug_log:
                debug_log(f"[BOLETO] Pendente sem número: {caminho} -> {movido or caminho}")
            cache[cache_key] = agora
            continue

        novo_nome = _nomear_boleto(info_boleto, caminho.name)
        log(f"BOLETO movendo para: {destino_dir} ({empresa})")
        movido = mover_pdf(caminho, destino_dir, log=log, novo_nome=novo_nome)
        if movido:
            movidos_info.append({"tipo": "boleto", "path": movido, "nf": (info_boleto.get("nf") or _extrair_nf_do_nome(movido.name))})
        cache[cache_key] = agora
    return movidos_info


def _tentar_criar_rascunhos(
    base_dir: Path,
    service,
    eventos: list[dict],
    estado_nf: dict[str, dict[str, Path]],
    nfs_rascunho: set[str],
    nfs_enviadas: set[str],
    report_state: dict[str, str],
    log=print,
):
    for ev in eventos:
        tipo = ev.get("tipo")
        nf = (ev.get("nf") or "").strip()
        path = ev.get("path")
        if tipo not in {"pdf", "xml", "boleto"} or not nf or not path:
            continue
        bucket = estado_nf.setdefault(nf, {})
        bucket[tipo] = path

    prontas = {}
    pendentes = {}
    for nf, bucket in list(estado_nf.items()):
        if nf in nfs_rascunho or nf in nfs_enviadas:
            continue
        if {"pdf", "xml", "boleto"}.issubset(bucket.keys()):
            prontas[nf] = bucket
        else:
            faltando = {"pdf", "xml", "boleto"} - set(bucket.keys())
            pendentes[nf] = ", ".join(sorted(faltando))

    if not prontas or not service:
        for nf, faltando in pendentes.items():
            status = "PENDENTE"
            motivo = f"Faltando: {faltando}"
            if report_state.get(nf) != f"{status}|{motivo}":
                _registrar_relatorio(base_dir, nf, status, motivo, log=log)
                report_state[nf] = f"{status}|{motivo}"
        return

    nao_enviadas = []
    houve_envios = False
    for nf, bucket in prontas.items():
        if _nf_enviada_gmail(service, nf, log=log):
            nfs_enviadas.add(nf)
            status = "JÁ ENVIADO"
            motivo = "E-mail já enviado"
            if report_state.get(nf) != f"{status}|{motivo}":
                _registrar_relatorio(base_dir, nf, status, motivo, log=log)
                report_state[nf] = f"{status}|{motivo}"
            houve_envios = True
            continue
        nao_enviadas.append((nf, bucket))

    if houve_envios:
        _salvar_nfs_enviadas(base_dir, nfs_enviadas, log=log)

    if nao_enviadas:
        resumo = ", ".join([f"NF {nf} - {_cliente_por_bucket(bucket)}" for nf, bucket in nao_enviadas])
        log(f"Os seguintes e-mails não foram enviados: {resumo}")

    for nf, bucket in nao_enviadas:
        assunto = f"XML PDF NF{nf} + BOLETO"
        corpo = _montar_corpo_email(base_dir, nf)
        anexos = [bucket["xml"], bucket["pdf"], bucket["boleto"]]
        draft_id = _criar_rascunho_gmail(service, assunto, corpo, anexos, log=log)
        if draft_id:
            nfs_rascunho.add(nf)
            _salvar_nfs_rascunho(base_dir, nfs_rascunho, log=log)
            log(f"Rascunho criado para NF{nf} (id={draft_id}).")
            status = "RASCUNHO CRIADO"
            motivo = "Rascunho criado com sucesso"
            if report_state.get(nf) != f"{status}|{motivo}":
                _registrar_relatorio(base_dir, nf, status, motivo, log=log)
                report_state[nf] = f"{status}|{motivo}"
        else:
            status = "FALHA AO CRIAR RASCUNHO"
            motivo = "Falha ao criar rascunho"
            if report_state.get(nf) != f"{status}|{motivo}":
                _registrar_relatorio(base_dir, nf, status, motivo, log=log)
                report_state[nf] = f"{status}|{motivo}"


def _coletar_eventos_existentes_mes_atual(
    destinos_pdf: list[Path],
    destinos_xml: list[Path],
    destinos_boleto: list[Path],
    log=print,
) -> list[dict]:
    eventos = []

    def pasta_ano_atual(base: Path) -> Path:
        hoje = datetime.now()
        return base / hoje.strftime("%Y")

    for base in destinos_pdf:
        pasta = pasta_ano_atual(base)
        if not pasta.exists():
            continue
        # PDFs ficam em subpastas de mês; varre o ano inteiro para compor trio entre meses.
        for p in pasta.rglob("*.pdf"):
            if not p.is_file():
                continue
            nf = _extrair_nf_do_nome(p.name)
            if nf:
                eventos.append({"tipo": "pdf", "path": p, "nf": nf})

    for base in destinos_boleto:
        if not base.exists():
            continue
        # Boletos podem estar em subpastas diferentes (ex.: "02-2026").
        for p in base.rglob("*.pdf"):
            if not p.is_file():
                continue
            nf = _extrair_nf_do_nome(p.name)
            if not nf:
                info = _extrair_info_boleto_pdf(p, log=log)
                nf = (info.get("nf") or "").strip() or None
            if nf:
                eventos.append({"tipo": "boleto", "path": p, "nf": nf})

    for base in destinos_xml:
        pasta = pasta_ano_atual(base)
        if not pasta.exists():
            continue
        # XMLs também ficam em subpastas de mês.
        for p in pasta.rglob("*.xml"):
            if not p.is_file():
                continue
            nf = _extrair_nf_do_nome(p.name)
            if not nf:
                txt = _ler_texto_arquivo(p) or ""
                nf = _extrair_nf_xml_texto(txt)
            if nf:
                eventos.append({"tipo": "xml", "path": p, "nf": nf})
    return eventos


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return _base_dir()




def _criar_icone_tray():
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    icon_path = None
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "favicon.ico"
        if candidate.exists():
            icon_path = candidate
        else:
            candidate = Path(sys._MEIPASS) / "icon.png"
            if candidate.exists():
                icon_path = candidate
    if not icon_path:
        candidate = _base_dir() / "favicon.ico"
        if candidate.exists():
            icon_path = candidate
        else:
            candidate = _base_dir() / "icon.png"
            if candidate.exists():
                icon_path = candidate
    if icon_path:
        try:
            return Image.open(icon_path)
        except Exception:
            pass
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, size - 6, size - 6), fill=(255, 105, 180, 255))
    return img


_config_window_lock = threading.Lock()
_config_process = None
_logs_process = None
_status_process = None
_update_thread = None


def _abrir_interface_config(base_dir: Path, log=print):
    try:
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QVBoxLayout,
            QGridLayout,
            QLineEdit,
            QPushButton,
            QLabel,
            QFileDialog,
            QMessageBox,
            QHBoxLayout,
            QCheckBox,
        )
        from PySide6.QtCore import Qt
    except Exception as e:
        log(f"PySide6 não encontrado para abrir Configuração: {e}")
        return

    cfg = _carregar_config(base_dir, log=log)
    campos = [
        ("Pasta observada (PDF)", "pdf_watch_dir"),
        ("Pasta observada (XML)", "xml_watch_dir"),
        ("Pasta observada (BOLETO)", "boleto_watch_dir"),
        ("Destino PDF MVA", "pdf_destino_mva"),
        ("Destino PDF HORIZONTE", "pdf_destino_horizonte"),
        ("Destino XML MVA", "xml_destino_mva"),
        ("Destino XML HORIZONTE", "xml_destino_horizonte"),
        ("Destino BOLETO MVA", "boleto_destino_mva"),
        ("Destino BOLETO HORIZONTE", "boleto_destino_horizonte"),
    ]

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Configuração de Pastas")
    dialog.setMinimumWidth(920)
    dialog.setModal(True)
    dialog.setStyleSheet("""
        QDialog { background: #2a170f; color: #ffffff; }
        QLabel { color: #ffffff; }
        QLabel#title { font-size: 22px; font-weight: 700; color: #ff9f43; }
        QLabel#subtitle { color: #ffd7b0; }
        QLabel.field { font-weight: 600; color: #ffd7b0; }
        QLineEdit {
            background: #3a2418; border: 1px solid #b86a27; border-radius: 8px;
            padding: 8px 10px; color: #ffffff;
        }
        QLineEdit:focus { border: 1px solid #ff9f43; }
        QPushButton.pick {
            background: #5a341d; color: #ffffff; border: 1px solid #b86a27; border-radius: 8px; padding: 8px 10px;
        }
        QPushButton.pick:hover { background: #6a3d21; }
        QPushButton:hover { background: #ff9f43; }
        QPushButton:pressed { background: #cc6d12; padding-top: 9px; padding-left: 11px; }
        QPushButton.save {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px; padding: 9px 14px; font-weight: 700;
        }
        QPushButton.cancel {
            background: #4b2b1a; color: #ffffff; border: 0; border-radius: 8px; padding: 9px 14px;
        }
        QMessageBox { background: #2a170f; color: #ffffff; }
        QMessageBox QLabel { color: #ffffff; }
        QMessageBox QPushButton {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px; padding: 6px 12px;
        }
    """)

    main_layout = QVBoxLayout(dialog)
    main_layout.setContentsMargins(22, 20, 22, 20)
    main_layout.setSpacing(12)

    titulo = QLabel("Configuração de Pastas")
    titulo.setObjectName("title")
    subtitulo = QLabel("Defina as pastas de origem e destino para PDF, XML e BOLETO.")
    subtitulo.setObjectName("subtitle")
    main_layout.addWidget(titulo)
    main_layout.addWidget(subtitulo)

    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(10)
    edits: dict[str, QLineEdit] = {}

    def selecionar_pasta(chave: str):
        atual = edits[chave].text().strip() or str(Path.home())
        selecionado = QFileDialog.getExistingDirectory(dialog, "Selecione o diretório", atual)
        if selecionado:
            edits[chave].setText(selecionado)

    for i, (texto, chave) in enumerate(campos):
        lbl = QLabel(texto)
        lbl.setProperty("class", "field")
        edit = QLineEdit(cfg.get(chave, ""))
        btn = QPushButton("Selecionar")
        btn.setProperty("class", "pick")
        btn.clicked.connect(lambda _=False, c=chave: selecionar_pasta(c))
        edits[chave] = edit
        grid.addWidget(lbl, i, 0)
        grid.addWidget(edit, i, 1)
        grid.addWidget(btn, i, 2)

    grid.setColumnStretch(1, 1)
    main_layout.addLayout(grid)

    chk_email = QCheckBox("Ativar criacao de rascunho de e-mail")
    chk_email.setChecked((cfg.get("email_enabled", "0").strip() == "1"))
    chk_email.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    main_layout.addWidget(chk_email)

    chk_debug = QCheckBox("Ativar debug detalhado (log técnico)")
    chk_debug.setChecked((cfg.get("debug_enabled", "0").strip() == "1"))
    chk_debug.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    main_layout.addWidget(chk_debug)

    chk_update = QCheckBox("Verificar atualização automaticamente")
    chk_update.setChecked((cfg.get("auto_update_enabled", "1").strip() == "1"))
    chk_update.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    main_layout.addWidget(chk_update)

    footer = QHBoxLayout()
    footer.addStretch(1)
    btn_cancelar = QPushButton("Cancelar")
    btn_cancelar.setProperty("class", "cancel")
    btn_salvar = QPushButton("Salvar")
    btn_salvar.setProperty("class", "save")
    footer.addWidget(btn_cancelar)
    footer.addWidget(btn_salvar)
    main_layout.addLayout(footer)

    def salvar():
        novo_cfg = {chave: edits[chave].text().strip() for _, chave in campos}
        novo_cfg["email_enabled"] = "1" if chk_email.isChecked() else "0"
        novo_cfg["debug_enabled"] = "1" if chk_debug.isChecked() else "0"
        novo_cfg["auto_update_enabled"] = "1" if chk_update.isChecked() else "0"
        faltantes = [k for k, v in novo_cfg.items() if not v]
        if faltantes:
            QMessageBox.warning(dialog, "Configuração", "Preencha todos os diretórios antes de salvar.")
            return
        try:
            _salvar_config(base_dir, novo_cfg)
            QMessageBox.information(dialog, "Configuração", f"Configuração salva em:\n{_config_path(base_dir)}")
            dialog.accept()
        except Exception as e:
            QMessageBox.critical(dialog, "Configuração", f"Falha ao salvar Configuração:\n{e}")

    btn_cancelar.clicked.connect(dialog.reject)
    btn_salvar.clicked.connect(salvar)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    dialog.exec()

    if created_app:
        app.quit()


def _abrir_interface_config_em_thread(base_dir: Path, log=print):
    global _config_process
    with _config_window_lock:
        if _config_process and _config_process.poll() is None:
            return
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--config"]
                cwd = str(Path(sys.executable).parent)
            else:
                cmd = [sys.executable, str(Path(__file__).resolve()), "--config"]
                cwd = str(base_dir)
            _config_process = subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            log(f"Falha ao abrir Configuração: {e}")


def _abrir_visualizador_logs(base_dir: Path, log=print):
    try:
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QVBoxLayout,
            QLabel,
            QHBoxLayout,
            QPushButton,
            QPlainTextEdit,
            QTabWidget,
            QWidget,
            QCheckBox,
        )
        from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher
        from PySide6.QtGui import QTextCursor
    except Exception as e:
        log(f"PySide6 não encontrado para abrir logs: {e}")
        return

    caminho_log = _log_path(base_dir)
    caminho_debug = _debug_log_path(base_dir)
    viewer_settings = _carregar_viewer_settings(base_dir, log=log)
    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Logs")
    dialog.setMinimumSize(980, 620)
    dialog.setModal(False)
    dialog.setStyleSheet("""
        QDialog { background: #2a170f; color: #ffffff; }
        QLabel { color: #ffffff; }
        QLabel#title { font-size: 20px; font-weight: 700; color: #ff9f43; }
        QLabel#subtitle { color: #ffd7b0; }
        QPlainTextEdit {
            background: #3a2418; color: #ffffff; border: 1px solid #b86a27;
            border-radius: 8px; padding: 8px; font-family: Consolas, monospace;
        }
        QPushButton {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px;
            padding: 8px 12px; font-weight: 600;
        }
        QPushButton.secondary { background: #4b2b1a; }
        QPushButton:hover { background: #ff9f43; }
        QPushButton:pressed { background: #cc6d12; padding-top: 9px; padding-left: 13px; }
        QTabWidget::pane { border: 1px solid #b86a27; border-radius: 8px; }
        QTabBar::tab {
            background: #4b2b1a; color: #ffd7b0; padding: 6px 12px; border-top-left-radius: 6px; border-top-right-radius: 6px;
        }
        QTabBar::tab:selected { background: #ff8a1f; color: #ffffff; }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title = QLabel("Visualizador de Logs")
    title.setObjectName("title")
    subtitle = QLabel(
        "Aqui você encontra o histórico do programa.\n"
        f"Log principal: {caminho_log}\n"
        f"Log técnico: {caminho_debug}"
    )
    subtitle.setObjectName("subtitle")
    layout.addWidget(title)
    layout.addWidget(subtitle)

    tabs = QTabWidget()
    text_main = QPlainTextEdit()
    text_main.setReadOnly(True)
    text_main.setMaximumBlockCount(4000)
    text_debug = QPlainTextEdit()
    text_debug.setReadOnly(True)
    text_debug.setMaximumBlockCount(4000)
    tabs.addTab(text_main, "Log principal")
    tabs.addTab(text_debug, "Log técnico (detalhado)")

    # Aba de configurações do visualizador
    settings_tab = QWidget()
    settings_layout = QVBoxLayout(settings_tab)
    settings_layout.setContentsMargins(14, 10, 14, 10)
    chk_show_dates = QCheckBox("Mostrar datas nos logs")
    chk_show_dates.setChecked(viewer_settings.get("show_dates", True))
    chk_show_time = QCheckBox("Mostrar hora nos logs")
    chk_show_time.setChecked(viewer_settings.get("show_time", False))
    chk_auto_scroll = QCheckBox("Auto‑rolar para o final")
    chk_auto_scroll.setChecked(viewer_settings.get("auto_scroll", False))
    chk_pause_refresh = QCheckBox("Pausar atualização automática")
    chk_pause_refresh.setChecked(viewer_settings.get("pause_refresh", False))
    chk_show_dates.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    chk_show_time.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    chk_auto_scroll.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    chk_pause_refresh.setStyleSheet("QCheckBox { color: #ffffff; font-weight: 600; }")
    btn_clear = QPushButton("Limpar log selecionado")
    btn_clear.setProperty("class", "secondary")
    settings_layout.addWidget(chk_show_dates)
    settings_layout.addWidget(chk_show_time)
    settings_layout.addWidget(chk_auto_scroll)
    settings_layout.addWidget(chk_pause_refresh)
    settings_layout.addWidget(btn_clear)
    settings_layout.addStretch(1)
    tabs.addTab(settings_tab, "⚙ Configurações")
    layout.addWidget(tabs, 1)

    actions = QHBoxLayout()
    btn_refresh = QPushButton("Atualizar")
    btn_check_update = QPushButton("Verificar atualização")
    btn_open = QPushButton("Abrir arquivo")
    btn_report = QPushButton("Relatório")
    btn_open.setProperty("class", "secondary")
    btn_close = QPushButton("Fechar")
    btn_close.setProperty("class", "secondary")
    actions.addWidget(btn_refresh)
    actions.addWidget(btn_check_update)
    actions.addWidget(btn_open)
    actions.addWidget(btn_report)
    actions.addStretch(1)
    actions.addWidget(btn_close)
    layout.addLayout(actions)

    max_chars = 200000
    tail_bytes = 320000
    estados = {
        "main": {"path": caminho_log, "widget": text_main, "offset": 0, "raw": ""},
        "debug": {"path": caminho_debug, "widget": text_debug, "offset": 0, "raw": ""},
    }
    pending_keys: set[str] = set()

    def _formatar_log(texto: str) -> str:
        linhas = []
        for linha in texto.splitlines():
            if linha.startswith("[") and "]" in linha:
                idx = linha.find("]")
                prefixo = linha[1:idx]
                resto = linha[idx + 1 :].lstrip()
                if not chk_show_dates.isChecked():
                    linhas.append(resto)
                    continue
                if " " in prefixo:
                    data, hora = prefixo.split(" ", 1)
                else:
                    data, hora = prefixo, ""
                if chk_show_time.isChecked() and hora:
                    linhas.append(f"[{data} {hora}] {resto}")
                else:
                    linhas.append(f"[{data}] {resto}")
                continue
            linhas.append(linha)
        return "\n".join(linhas)

    def _renderizar_chave(chave: str, force_bottom: bool = False):
        estado = estados[chave]
        widget: QPlainTextEdit = estado["widget"]
        raw = estado["raw"] or ""
        if not raw and not estado["path"].exists():
            widget.setPlainText("O log ainda não foi criado.")
            return
        try:
            bar = widget.verticalScrollBar()
            at_bottom = bar.value() >= (bar.maximum() - 5)
            prev_value = bar.value()
            exibicao = _formatar_log(raw)
            widget.setPlainText(exibicao)
            if chk_auto_scroll.isChecked() and (at_bottom or force_bottom):
                widget.moveCursor(QTextCursor.End)
            else:
                bar.setValue(prev_value)
        except Exception as e:
            widget.setPlainText(f"Falha ao ler o log: {e}")

    def _ler_cauda(path: Path) -> tuple[str, int]:
        if not path.exists():
            return "", 0
        try:
            size = path.stat().st_size
            start = max(0, size - tail_bytes)
            with path.open("rb") as f:
                if start:
                    f.seek(start)
                data = f.read()
            texto = data.decode("utf-8", errors="ignore")
            return texto[-max_chars:], size
        except Exception:
            try:
                texto = path.read_text(encoding="utf-8", errors="ignore")
                return texto[-max_chars:], path.stat().st_size
            except Exception:
                return "", 0

    def _recarregar_completo(chave: str, force_bottom: bool = False):
        estado = estados[chave]
        texto, size = _ler_cauda(estado["path"])
        estado["raw"] = texto
        estado["offset"] = size
        _renderizar_chave(chave, force_bottom=force_bottom)

    def _atualizar_incremental(chave: str):
        estado = estados[chave]
        path: Path = estado["path"]
        if not path.exists():
            estado["raw"] = ""
            estado["offset"] = 0
            _renderizar_chave(chave)
            return
        try:
            size = path.stat().st_size
        except Exception:
            _recarregar_completo(chave)
            return

        offset = int(estado["offset"] or 0)
        if size < offset:
            _recarregar_completo(chave)
            return
        if size == offset:
            return
        try:
            with path.open("rb") as f:
                f.seek(offset)
                data = f.read()
            delta = data.decode("utf-8", errors="ignore")
            estado["offset"] = size
            estado["raw"] = ((estado["raw"] or "") + delta)[-max_chars:]
            _renderizar_chave(chave)
        except Exception:
            _recarregar_completo(chave)

    def carregar_ativos(force_full: bool = False):
        if force_full:
            _recarregar_completo("main", force_bottom=True)
            _recarregar_completo("debug", force_bottom=True)
            return
        agendar_atualizacao({"main", "debug"}, delay_ms=0)

    def abrir_arquivo():
        try:
            idx = tabs.currentIndex()
            path = caminho_log if idx == 0 else caminho_debug
            if path.exists():
                os.startfile(str(path))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
                os.startfile(str(path))
        except Exception as e:
            log(f"Falha ao abrir arquivo de log: {e}")

    debounce = QTimer(dialog)
    debounce.setSingleShot(True)
    debounce.setInterval(180)

    def processar_pendencias():
        if chk_pause_refresh.isChecked():
            return
        keys = list(pending_keys)
        pending_keys.clear()
        for chave in keys:
            _atualizar_incremental(chave)

    debounce.timeout.connect(processar_pendencias)

    watcher = QFileSystemWatcher(dialog)
    watched_dirs = {str(caminho_log.parent), str(caminho_debug.parent)}
    watcher.addPaths(list(watched_dirs))

    def _watched_files() -> set[str]:
        return set(watcher.files())

    def _garantir_watch_arquivo(path: Path):
        p = str(path)
        if path.exists() and p not in _watched_files():
            watcher.addPath(p)

    _garantir_watch_arquivo(caminho_log)
    _garantir_watch_arquivo(caminho_debug)

    def _chave_por_caminho(caminho: str) -> str | None:
        if Path(caminho) == caminho_log:
            return "main"
        if Path(caminho) == caminho_debug:
            return "debug"
        return None

    def agendar_atualizacao(chaves: set[str], delay_ms: int = 180):
        if chk_pause_refresh.isChecked():
            return
        pending_keys.update(chaves)
        debounce.start(max(0, delay_ms))

    def on_file_changed(caminho: str):
        chave = _chave_por_caminho(caminho)
        if chave:
            _garantir_watch_arquivo(estados[chave]["path"])
            agendar_atualizacao({chave})

    def on_dir_changed(caminho: str):
        chaves = set()
        for chave, estado in estados.items():
            if str(estado["path"].parent) == caminho:
                _garantir_watch_arquivo(estado["path"])
                chaves.add(chave)
        if chaves:
            agendar_atualizacao(chaves)

    watcher.fileChanged.connect(on_file_changed)
    watcher.directoryChanged.connect(on_dir_changed)

    timer = QTimer(dialog)
    timer.setInterval(12000)
    timer.timeout.connect(lambda: agendar_atualizacao({"main", "debug"}))
    timer.start()

    def atualizar_timer():
        if chk_pause_refresh.isChecked():
            pending_keys.clear()
            debounce.stop()
            timer.stop()
        else:
            if not timer.isActive():
                timer.start()
            agendar_atualizacao({"main", "debug"}, delay_ms=0)

    def limpar_log():
        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(dialog)
            box.setWindowTitle("Limpar logs")
            box.setText("Qual log você deseja limpar?")
            btn_main = box.addButton("Log principal", QMessageBox.AcceptRole)
            btn_debug = box.addButton("Log técnico", QMessageBox.AcceptRole)
            btn_report = box.addButton("Relatório", QMessageBox.AcceptRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == btn_main:
                path = caminho_log
                chave = "main"
            elif clicked == btn_debug:
                path = caminho_debug
                chave = "debug"
            elif clicked == btn_report:
                path = _report_path(base_dir)
                chave = None
            else:
                return
        except Exception:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except Exception as e:
            log(f"Falha ao limpar log: {e}")
        if chave:
            _recarregar_completo(chave, force_bottom=True)
            _garantir_watch_arquivo(path)
        else:
            carregar_ativos(force_full=True)

    def salvar_viewer():
        _salvar_viewer_settings(
            base_dir,
            {
                "show_dates": chk_show_dates.isChecked(),
                "show_time": chk_show_time.isChecked(),
                "auto_scroll": chk_auto_scroll.isChecked(),
                "pause_refresh": chk_pause_refresh.isChecked(),
            },
            log=log,
        )

    btn_refresh.clicked.connect(lambda: carregar_ativos(force_full=True))
    btn_check_update.clicked.connect(
        lambda: _verificar_atualizacao_github(
            base_dir,
            log=log,
            prompt=True,
            notify=True,
            exit_on_success=True,
            use_native_dialogs=False,
        )
    )
    btn_open.clicked.connect(abrir_arquivo)
    btn_report.clicked.connect(lambda: _abrir_relatorio(base_dir, log=log))
    btn_close.clicked.connect(dialog.close)
    chk_show_dates.stateChanged.connect(lambda *_: (salvar_viewer(), _renderizar_chave("main"), _renderizar_chave("debug")))
    chk_show_time.stateChanged.connect(lambda *_: (salvar_viewer(), _renderizar_chave("main"), _renderizar_chave("debug")))
    chk_auto_scroll.stateChanged.connect(lambda *_: (salvar_viewer(), carregar_ativos()))
    chk_pause_refresh.stateChanged.connect(lambda *_: (salvar_viewer(), atualizar_timer()))
    btn_clear.clicked.connect(limpar_log)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    _recarregar_completo("main", force_bottom=True)
    _recarregar_completo("debug", force_bottom=True)
    dialog.exec()

    if created_app:
        app.quit()


def _abrir_visualizador_logs_em_thread(base_dir: Path, log=print):
    global _logs_process
    with _config_window_lock:
        if _logs_process and _logs_process.poll() is None:
            return
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--logs"]
                cwd = str(Path(sys.executable).parent)
            else:
                cmd = [sys.executable, str(Path(__file__).resolve()), "--logs"]
                cwd = str(base_dir)
            _logs_process = subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            log(f"Falha ao abrir visualizador de logs: {e}")


def _abrir_status(base_dir: Path, log=print):
    try:
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QVBoxLayout,
            QLabel,
            QHBoxLayout,
            QPushButton,
            QProgressBar,
            QGridLayout,
        )
        from PySide6.QtCore import Qt, QTimer
    except Exception as e:
        log(f"PySide6 não encontrado para abrir status: {e}")
        return

    def _formatar_data_status(valor: str) -> str:
        txt = (valor or "").strip()
        if not txt:
            return "—"
        try:
            return datetime.fromisoformat(txt).strftime("%d/%m/%Y %H:%M:%S")
        except Exception:
            return txt

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Status")
    dialog.setMinimumSize(620, 320)
    dialog.setModal(False)
    dialog.setStyleSheet("""
        QDialog { background: #2a170f; color: #ffffff; }
        QLabel { color: #ffffff; }
        QLabel#title { font-size: 20px; font-weight: 700; color: #ff9f43; }
        QLabel#subtitle { color: #ffd7b0; }
        QLabel#value { color: #ffffff; font-weight: 600; }
        QLabel#muted { color: #ffd7b0; }
        QProgressBar {
            background: #3a2418; border: 1px solid #b86a27; border-radius: 8px;
            text-align: center; color: #ffffff; min-height: 18px;
        }
        QProgressBar::chunk { background: #ff8a1f; border-radius: 7px; }
        QPushButton {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px;
            padding: 8px 12px; font-weight: 600;
        }
        QPushButton.secondary { background: #4b2b1a; }
        QPushButton:hover { background: #ff9f43; }
        QPushButton:pressed { background: #cc6d12; padding-top: 9px; padding-left: 13px; }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title = QLabel("Status do monitor")
    title.setObjectName("title")
    subtitle = QLabel("Acompanhe a etapa atual, o tempo do último ciclo e quando a pasta será analisada novamente.")
    subtitle.setObjectName("subtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(subtitle)

    progress = QProgressBar()
    progress.setTextVisible(True)
    progress.setRange(0, 100)
    progress.setValue(0)
    layout.addWidget(progress)

    phase = QLabel("Parado")
    phase.setObjectName("value")
    detail = QLabel("Aguardando inicialização.")
    detail.setWordWrap(True)
    detail.setObjectName("muted")
    layout.addWidget(phase)
    layout.addWidget(detail)

    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(8)
    campos = {
        "intervalo": QLabel("—"),
        "ciclo": QLabel("—"),
        "fim": QLabel("—"),
        "historico": QLabel("—"),
        "eventos": QLabel("—"),
        "atualizado": QLabel("—"),
    }
    for lbl in campos.values():
        lbl.setObjectName("value")

    itens = [
        ("Novo ciclo após", "intervalo"),
        ("Último ciclo", "ciclo"),
        ("Última conclusão", "fim"),
        ("Varredura inicial", "historico"),
        ("Últimos eventos", "eventos"),
        ("Status atualizado em", "atualizado"),
    ]
    for idx, (texto, chave) in enumerate(itens):
        lbl = QLabel(texto)
        lbl.setObjectName("muted")
        grid.addWidget(lbl, idx, 0)
        grid.addWidget(campos[chave], idx, 1)
    grid.setColumnStretch(1, 1)
    layout.addLayout(grid)

    actions = QHBoxLayout()
    btn_refresh = QPushButton("Atualizar")
    btn_logs = QPushButton("Ver logs")
    btn_logs.setProperty("class", "secondary")
    btn_close = QPushButton("Fechar")
    btn_close.setProperty("class", "secondary")
    actions.addWidget(btn_refresh)
    actions.addWidget(btn_logs)
    actions.addStretch(1)
    actions.addWidget(btn_close)
    layout.addLayout(actions)

    def carregar():
        status = _carregar_status(base_dir, log=log)
        busy = bool(status.get("busy"))
        if busy:
            progress.setRange(0, 0)
            progress.setFormat("Processando...")
        else:
            progress.setRange(0, 100)
            progress.setValue(100)
            progress.setFormat("Em espera")
        phase.setText(str(status.get("phase") or "Parado"))
        detail.setText(str(status.get("detail") or "Aguardando."))
        intervalo = int(status.get("scan_interval_seconds") or 0)
        campos["intervalo"].setText(f"{intervalo}s" if intervalo > 0 else "—")
        ciclo = float(status.get("last_cycle_seconds") or 0.0)
        campos["ciclo"].setText(f"{ciclo:.2f}s" if ciclo > 0 else "—")
        historico = float(status.get("last_existing_scan_seconds") or 0.0)
        campos["historico"].setText(f"{historico:.2f}s" if historico > 0 else "—")
        campos["fim"].setText(_formatar_data_status(str(status.get("last_cycle_finished_at") or "")))
        campos["atualizado"].setText(_formatar_data_status(str(status.get("updated_at") or "")))
        eventos_txt = (
            f"Total {int(status.get('last_events_total') or 0)} | "
            f"PDF {int(status.get('last_pdf_events') or 0)} | "
            f"XML {int(status.get('last_xml_events') or 0)} | "
            f"Boleto {int(status.get('last_boleto_events') or 0)}"
        )
        campos["eventos"].setText(eventos_txt)

    timer = QTimer(dialog)
    timer.setInterval(900)
    timer.timeout.connect(carregar)
    timer.start()

    btn_refresh.clicked.connect(carregar)
    btn_logs.clicked.connect(lambda: _abrir_visualizador_logs_em_thread(base_dir, log=log))
    btn_close.clicked.connect(dialog.close)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    carregar()
    dialog.exec()

    if created_app:
        app.quit()


def _abrir_status_em_thread(base_dir: Path, log=print):
    global _status_process
    with _config_window_lock:
        if _status_process and _status_process.poll() is None:
            return
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--status"]
                cwd = str(Path(sys.executable).parent)
            else:
                cmd = [sys.executable, str(Path(__file__).resolve()), "--status"]
                cwd = str(base_dir)
            _status_process = subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            log(f"Falha ao abrir status: {e}")


def _abrir_relatorio(base_dir: Path, log=print):
    try:
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QVBoxLayout,
            QLabel,
            QHBoxLayout,
            QPushButton,
            QTextEdit,
        )
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QTextCursor
    except Exception as e:
        log(f"PySide6 não encontrado para abrir relatório: {e}")
        return

    caminho = _report_path(base_dir)
    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Relatório")
    dialog.setMinimumSize(980, 620)
    dialog.setModal(False)
    dialog.setStyleSheet("""
        QDialog { background: #2a170f; color: #ffffff; }
        QLabel { color: #ffffff; }
        QLabel#title { font-size: 20px; font-weight: 700; color: #ff9f43; }
        QLabel#subtitle { color: #ffd7b0; }
        QTextEdit {
            background: #3a2418; color: #ffffff; border: 1px solid #b86a27;
            border-radius: 8px; padding: 8px; font-family: Consolas, monospace;
        }
        QPushButton {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px;
            padding: 8px 12px; font-weight: 600;
        }
        QPushButton.secondary { background: #4b2b1a; }
        QPushButton:hover { background: #ff9f43; }
        QPushButton:pressed { background: #cc6d12; padding-top: 9px; padding-left: 13px; }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)

    title = QLabel("Relatório de e-mails")
    title.setObjectName("title")
    subtitle = QLabel(
        "Este relatório mostra o status dos e-mails e o motivo de cada decisão.\n"
        "Legenda: RASCUNHO CRIADO, JÁ ENVIADO, PENDENTE, FALHA AO CRIAR RASCUNHO.\n"
        f"Arquivo: {caminho}"
    )
    subtitle.setObjectName("subtitle")
    layout.addWidget(title)
    layout.addWidget(subtitle)

    text = QTextEdit()
    text.setReadOnly(True)
    layout.addWidget(text, 1)

    actions = QHBoxLayout()
    btn_refresh = QPushButton("Atualizar")
    btn_open = QPushButton("Abrir arquivo")
    btn_open.setProperty("class", "secondary")
    btn_close = QPushButton("Fechar")
    btn_close.setProperty("class", "secondary")
    actions.addWidget(btn_refresh)
    actions.addWidget(btn_open)
    actions.addStretch(1)
    actions.addWidget(btn_close)
    layout.addLayout(actions)

    def carregar():
        if not caminho.exists():
            text.setPlainText("O relatório ainda não foi criado.")
            return
        try:
            bar = text.verticalScrollBar()
            at_bottom = bar.value() >= (bar.maximum() - 5)
            prev_value = bar.value()
            conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
            text.setPlainText(conteudo[-200000:])
            if at_bottom:
                text.moveCursor(QTextCursor.End)
            else:
                bar.setValue(prev_value)
        except Exception as e:
            text.setPlainText(f"Falha ao ler o relatório: {e}")

    def abrir_arquivo():
        try:
            if caminho.exists():
                os.startfile(str(caminho))
            else:
                caminho.parent.mkdir(parents=True, exist_ok=True)
                caminho.write_text("", encoding="utf-8")
                os.startfile(str(caminho))
        except Exception as e:
            log(f"Falha ao abrir arquivo de relatório: {e}")

    timer = QTimer(dialog)
    timer.setInterval(3000)
    timer.timeout.connect(carregar)
    timer.start()

    btn_refresh.clicked.connect(carregar)
    btn_open.clicked.connect(abrir_arquivo)
    btn_close.clicked.connect(dialog.close)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    carregar()
    dialog.exec()

    if created_app:
        app.quit()


def _garantir_arquivos_iniciais(base_dir: Path, log=print) -> bool:
    cfg_path = _config_path(base_dir)
    first_run = not cfg_path.exists()
    try:
        if first_run:
            _salvar_config(base_dir, _default_paths(base_dir))
        _state_path(base_dir).touch(exist_ok=True)
        _sent_state_path(base_dir).touch(exist_ok=True)
        p_log = _log_path(base_dir)
        p_log.parent.mkdir(parents=True, exist_ok=True)
        p_log.touch(exist_ok=True)
        if not _status_path(base_dir).exists():
            _salvar_status(base_dir, _status_padrao(), log=log)
    except Exception as e:
        log(f"Falha ao preparar arquivos iniciais: {e}")
    return first_run


def _parse_version(tag: str) -> tuple[int, ...]:
    tag = (tag or "").strip().lstrip("vV")
    if not tag:
        return (0,)
    nums = []
    for part in tag.split("."):
        digits = re.sub(r"[^0-9]", "", part)
        nums.append(int(digits) if digits else 0)
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    return tuple(nums or [0])


def _notificar_usuario_atualizacao(titulo: str, mensagem: str, prefer_native: bool = False) -> None:
    if prefer_native:
        try:
            ctypes.windll.user32.MessageBoxW(None, mensagem, titulo, 0x40)
            return
        except Exception:
            pass
    try:
        from PySide6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(None, titulo, mensagem)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(None, mensagem, titulo, 0x40)
    except Exception:
        pass


def _verificar_atualizacao_github(
    base_dir: Path,
    log=print,
    prompt=True,
    notify=False,
    exit_on_success=False,
    use_native_dialogs=False,
) -> bool:
    repo = GITHUB_REPO
    if not getattr(sys, "frozen", False):
        msg = "Verificação de atualização só funciona no executável (.exe)."
        log(msg)
        if notify:
            _notificar_usuario_atualizacao("Atualização", msg, prefer_native=use_native_dialogs)
        return False
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PdfWatcher",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"Falha ao verificar atualização: {e}")
        if notify:
            _notificar_usuario_atualizacao("Atualização", f"Falha ao verificar atualização.\n{e}", prefer_native=use_native_dialogs)
        return False

    tag = data.get("tag_name") or data.get("name") or ""
    latest = _parse_version(tag)
    current = _parse_version(APP_VERSION)
    if latest <= current:
        msg = f"Você já está na versão mais recente ({APP_VERSION})."
        log(f"Atualização: {msg}")
        if notify:
            _notificar_usuario_atualizacao("Atualização", msg, prefer_native=use_native_dialogs)
        return False

    assets = data.get("assets") or []
    exe_url = None
    exe_name = None
    for a in assets:
        name = a.get("name") or ""
        if name.lower().endswith(".exe"):
            exe_url = a.get("browser_download_url")
            exe_name = name
            break
    if not exe_url:
        msg = "Atualização encontrada, mas nenhum .exe foi encontrado nos arquivos do release."
        log(msg)
        if notify:
            _notificar_usuario_atualizacao("Atualização", msg, prefer_native=use_native_dialogs)
        return False

    if prompt:
        if use_native_dialogs:
            try:
                MB_YESNO = 0x04
                MB_ICONQUESTION = 0x20
                IDYES = 6
                r = ctypes.windll.user32.MessageBoxW(
                    None,
                    f"Nova versão encontrada ({tag}).\nDeseja atualizar agora?",
                    "Atualização",
                    MB_YESNO | MB_ICONQUESTION,
                )
                if r != IDYES:
                    return False
            except Exception:
                pass
        else:
            try:
                from PySide6.QtWidgets import QMessageBox, QApplication
                app = QApplication.instance() or QApplication(sys.argv)
                r = QMessageBox.question(
                    None,
                    "Atualização",
                    f"Nova versão encontrada ({tag}).\nDeseja atualizar agora?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if r != QMessageBox.Yes:
                    return False
            except Exception:
                pass

    try:
        temp_dir = Path(tempfile.gettempdir())
        destino = temp_dir / exe_name
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(exe_url, context=ctx) as r, open(destino, "wb") as f:
                f.write(r.read())
        except Exception:
            urllib.request.urlretrieve(exe_url, destino)
        log(f"Atualização baixada: {destino}")

        exe_atual = Path(sys.executable)
        pid = os.getpid()
        bat = temp_dir / "update.bat"
        bat.write_text(
            "\n".join([
                "@echo off",
                f"set PID={pid}",
                f"set OLD_EXE={exe_atual}",
                f"set NEW_EXE={destino}",
                "timeout /t 2 /nobreak >nul",
                ":wait",
                "tasklist /FI \"PID eq %PID%\" 2>nul | findstr /I \"%PID%\" >nul",
                "if %errorlevel%==0 (timeout /t 1 >nul & goto wait)",
                "move /Y \"%NEW_EXE%\" \"%OLD_EXE%\"",
                "set PYINSTALLER_RESET_ENVIRONMENT=1",
                "set _PYI_ARCHIVE_FILE=",
                "set _PYI_APPLICATION_HOME_DIR=",
                "set _PYI_PARENT_PROCESS_LEVEL=",
                "set _MEIPASS2=",
                "start \"\" \"%OLD_EXE%\"",
                "del \"%~f0\"",
            ]),
            encoding="utf-8",
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        restart_env = os.environ.copy()
        restart_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for env_name in ("_PYI_ARCHIVE_FILE", "_PYI_APPLICATION_HOME_DIR", "_PYI_PARENT_PROCESS_LEVEL", "_MEIPASS2"):
            restart_env.pop(env_name, None)
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass
        subprocess.Popen(["cmd", "/c", str(bat)], shell=False, creationflags=creationflags, env=restart_env)
        if exit_on_success:
            log("Atualização iniciada. Encerrando o aplicativo...")
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.quit()
            except Exception:
                pass
            # Em verificações manuais (tray/tela de logs), sem este encerramento o .bat fica aguardando o PID.
            os._exit(0)
        return True
    except Exception as e:
        log(f"Falha ao baixar atualização: {e}")
        if notify:
            _notificar_usuario_atualizacao("Atualização", f"Falha ao baixar atualização.\n{e}", prefer_native=use_native_dialogs)
        return False


def _verificar_atualizacao_manual(base_dir: Path, log=print) -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        _verificar_atualizacao_github(
            base_dir,
            log=log,
            prompt=True,
            notify=True,
            exit_on_success=True,
            use_native_dialogs=False,
        )
        return

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True
    try:
        _verificar_atualizacao_github(
            base_dir,
            log=log,
            prompt=True,
            notify=True,
            exit_on_success=True,
            use_native_dialogs=False,
        )
    finally:
        if created_app:
            app.quit()


def _verificar_atualizacao_em_thread(base_dir: Path, log=print):
    global _update_thread
    with _config_window_lock:
        if _update_thread and _update_thread.is_alive():
            return

        def _worker():
            global _update_thread
            try:
                # Run the update flow inside the main app process so the restarted EXE
                # does not collide with a still-running primary instance.
                _verificar_atualizacao_github(
                    base_dir,
                    log=log,
                    prompt=True,
                    notify=True,
                    exit_on_success=True,
                    use_native_dialogs=True,
                )
            finally:
                with _config_window_lock:
                    _update_thread = None

        _update_thread = threading.Thread(
            target=_worker,
            name="PdfWatcherUpdateCheck",
            daemon=True,
        )
        _update_thread.start()

def _fluxo_primeira_execucao(base_dir: Path, log=print):
    first_run = not _config_path(base_dir).exists()
    if not first_run:
        return
    try:
        from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox
        from PySide6.QtCore import Qt
    except Exception:
        _garantir_arquivos_iniciais(base_dir, log=log)
        return

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Inicializando")
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    dialog.setModal(True)
    dialog.setMinimumWidth(520)
    dialog.setStyleSheet(
        "QDialog{background:#2a170f;color:#fff;} QLabel{color:#fff;} "
        "QProgressBar{background:#3a2418;border:1px solid #b86a27;border-radius:7px;text-align:center;color:#fff;} "
        "QProgressBar::chunk{background:#ff8a1f;border-radius:6px;}"
    )
    lay = QVBoxLayout(dialog)
    lbl = QLabel("Preparando ambiente inicial...")
    bar = QProgressBar()
    bar.setRange(0, 100)
    lay.addWidget(lbl)
    lay.addWidget(bar)

    dialog.show()
    app.processEvents()

    passos = [
        (20, "Criando configuracao inicial..."),
        (45, "Criando registro de NFs processadas..."),
        (70, "Preparando pasta de logs..."),
        (100, "Concluindo inicializacao..."),
    ]
    for pct, texto in passos:
        lbl.setText(texto)
        bar.setValue(pct)
        app.processEvents()
        time.sleep(0.18)

    _garantir_arquivos_iniciais(base_dir, log=log)
    dialog.close()
    QMessageBox.information(None, "Primeira execucao", "Inicializacao concluida com sucesso.")
    r = QMessageBox.question(
        None,
        "Rascunho de e-mail",
        "Deseja ativar a criação de rascunhos de e-mail agora?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    cfg = _carregar_config(base_dir, log=log)
    if r == QMessageBox.Yes:
        cfg["email_enabled"] = "1"
        _salvar_config(base_dir, cfg)
    else:
        cfg["email_enabled"] = "0"
        _salvar_config(base_dir, cfg)
        _abrir_interface_config(base_dir, log=log)
    if created_app:
        app.quit()


def _run_loop(stop_event: threading.Event, log):
    base_dir = _base_dir()
    log_path = _log_path(base_dir)
    debug_log_path = _debug_log_path(base_dir)
    def inner_log(msg: str):
        _log(msg, log_path)
    def inner_debug(msg: str):
        _log(msg, debug_log_path)

    log = log or inner_log

    nome_arquivo = os.getenv("PDF_NOME", "").strip()
    padrao_regex = os.getenv("PDF_PATTERN", "").strip()
    if "\\\\" in padrao_regex:
        padrao_regex = padrao_regex.replace("\\\\", "\\")
    texto_mva = os.getenv("PDF_TEXT_MATCH_MVA", "MVA").strip()
    texto_horizonte = os.getenv("PDF_TEXT_MATCH_HORIZONTE", "HORIZONTE").strip()
    cnpj_mva = os.getenv("XML_CNPJ_MVA", "18471209000107").strip()
    cnpj_horizonte = os.getenv("XML_CNPJ_HORIZONTE", "34636193000193").strip()
    permitir_todos = os.getenv("PDF_ALLOW_ALL", "").strip() == "1"
    intervalo = int(os.getenv("PDF_POLL_INTERVAL", "2"))

    log("Monitorando PDFs/XML/BOLETOS (Ctrl+C para sair).")
    if not texto_mva and not texto_horizonte:
        if permitir_todos:
            log("Filtro de texto vazio. PDF_ALLOW_ALL=1 ativo: moverá qualquer PDF que passe pelo nome.")
        else:
            log("Filtro de texto vazio. Nenhum PDF será movido até configurar PDF_TEXT_MATCH_MVA/HORIZONTE.")
    avisados = set()
    cache = {}
    cache_ttl = int(os.getenv("PDF_CACHE_TTL", "3600"))
    assinatura_cfg = None
    estado_nf = {}
    nfs_rascunho = _carregar_nfs_rascunho(base_dir, log=log)
    nfs_enviadas = _carregar_nfs_enviadas(base_dir, log=log)
    report_state = _carregar_report_state(base_dir, log=log)
    gmail_service = None
    email_ativo = False
    debug_ativo = False
    last_state_reload = time.time()
    last_update_check = 0.0
    update_interval = int(os.getenv("UPDATE_CHECK_INTERVAL", "3600"))
    last_existing_scan_seconds = 0.0

    def atualizar_status(phase: str, detail: str, busy: bool = True, **extra):
        payload = {
            "busy": busy,
            "phase": phase,
            "detail": detail,
            "scan_interval_seconds": intervalo,
            "last_existing_scan_seconds": last_existing_scan_seconds,
        }
        payload.update(extra)
        _salvar_status(base_dir, payload, log=log)

    while not stop_event.is_set():
        cycle_started_at = time.perf_counter()
        atualizar_status("Lendo configuração", "Atualizando pastas observadas e preferências...", busy=True)
        cfg = _carregar_config(base_dir, log=log)
        origem_pdf = Path(cfg["pdf_watch_dir"])
        origem_xml = Path(cfg["xml_watch_dir"])
        origem_boleto = Path(cfg["boleto_watch_dir"])
        destino_mva = Path(cfg["pdf_destino_mva"])
        destino_horizonte = Path(cfg["pdf_destino_horizonte"])
        destinos_xml = _carregar_diretorios_xml(cfg)
        destino_boleto_mva = Path(cfg["boleto_destino_mva"])
        destino_boleto_horizonte = Path(cfg["boleto_destino_horizonte"])
        email_ativo_novo = (cfg.get("email_enabled", "0").strip() == "1")
        debug_ativo_novo = (cfg.get("debug_enabled", "0").strip() == "1")
        debug_log = inner_debug if debug_ativo_novo else None
        eventos = []

        nova_assinatura = (
            str(origem_pdf),
            str(origem_xml),
            str(origem_boleto),
            str(destino_mva),
            str(destino_horizonte),
            str(destinos_xml["MVA"]),
            str(destinos_xml["HORIZONTE"]),
            str(destino_boleto_mva),
            str(destino_boleto_horizonte),
            email_ativo_novo,
            debug_ativo_novo,
        )
        if nova_assinatura != assinatura_cfg:
            assinatura_cfg = nova_assinatura
            log("Configuração carregada com sucesso.")
            log(f"Rascunho de e-mail: {'ATIVO' if email_ativo_novo else 'DESATIVADO'}")
            log(f"Debug detalhado: {'ATIVO' if debug_ativo_novo else 'DESATIVADO'}")
            if debug_log:
                debug_log(f"[CFG] Pasta observada PDF: {origem_pdf}")
                debug_log(f"[CFG] Pasta observada XML: {origem_xml}")
                debug_log(f"[CFG] Pasta observada BOLETO: {origem_boleto}")
                debug_log(f"[CFG] Destino PDF MVA: {destino_mva}")
                debug_log(f"[CFG] Destino PDF HORIZONTE: {destino_horizonte}")
                debug_log(f"[CFG] Destino XML MVA: {destinos_xml['MVA']}")
                debug_log(f"[CFG] Destino XML HORIZONTE: {destinos_xml['HORIZONTE']}")
                debug_log(f"[CFG] Destino BOLETO MVA: {destino_boleto_mva}")
                debug_log(f"[CFG] Destino BOLETO HORIZONTE: {destino_boleto_horizonte}")
            if email_ativo_novo and not email_ativo:
                gmail_service = _gmail_service(base_dir, log=log)
                if gmail_service:
                    log("Integração Gmail pronta. Rascunhos serão criados quando houver XML+PDF+BOLETO da mesma NF.")
                else:
                    log("Gmail indisponível no momento. O monitoramento de arquivos seguirá normalmente.")
            if not email_ativo_novo:
                gmail_service = None
            email_ativo = email_ativo_novo
            debug_ativo = debug_ativo_novo
            # Ao iniciar (ou ao trocar configuração), tenta compor trio PDF/XML/BOLETO
            # já existente nas pastas de destino do mês atual.
            atualizar_status("Sincronizando histórico", "Lendo arquivos já existentes nas pastas de destino...", busy=True)
            existing_scan_started = time.perf_counter()
            eventos.extend(
                _coletar_eventos_existentes_mes_atual(
                    [destino_mva, destino_horizonte],
                    [destinos_xml["MVA"], destinos_xml["HORIZONTE"]],
                    [destino_boleto_mva, destino_boleto_horizonte],
                    log=log,
                )
            )
            last_existing_scan_seconds = round(time.perf_counter() - existing_scan_started, 3)

        if debug_log:
            def _count_dir(path: Path) -> int:
                try:
                    return len(os.listdir(path))
                except Exception:
                    return -1
            debug_log(f"[LOOP] tick {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            debug_log(f"[LOOP] origem PDF itens: {_count_dir(origem_pdf)}")
            debug_log(f"[LOOP] origem XML itens: {_count_dir(origem_xml)}")
            debug_log(f"[LOOP] origem BOLETO itens: {_count_dir(origem_boleto)}")

        atualizar_status("Analisando PDFs", f"Lendo PDFs em {origem_pdf}...", busy=True)
        if origem_pdf.exists():
            if permitir_todos or texto_mva or texto_horizonte:
                eventos.extend(processar_pdfs(origem_pdf, destino_mva, destino_horizonte, nome_arquivo, padrao_regex, texto_mva, texto_horizonte, cache, log=log, debug_log=debug_log))
        else:
            chave_pdf = ("PDF", origem_pdf)
            if chave_pdf not in avisados:
                log(f"Diretório não encontrado (PDF): {origem_pdf}")
                avisados.add(chave_pdf)
            if debug_log:
                debug_log(f"[PDF] Diretório não encontrado: {origem_pdf}")

        atualizar_status("Analisando XMLs", f"Lendo XMLs em {origem_xml}...", busy=True)
        if origem_xml.exists():
            eventos.extend(processar_xmls(origem_xml, destinos_xml, cnpj_mva, cnpj_horizonte, cache, log=log, debug_log=debug_log))
        else:
            chave_xml = ("XML", origem_xml)
            if chave_xml not in avisados:
                log(f"Diretório não encontrado (XML): {origem_xml}")
                avisados.add(chave_xml)
            if debug_log:
                debug_log(f"[XML] Diretório não encontrado: {origem_xml}")

        atualizar_status("Analisando boletos", f"Lendo boletos em {origem_boleto}...", busy=True)
        if origem_boleto.exists():
            eventos.extend(
                processar_boletos(
                    origem_boleto,
                    destino_boleto_mva,
                    destino_boleto_horizonte,
                    cnpj_mva,
                    cnpj_horizonte,
                    cache,
                    workspace_dir=base_dir,
                    log=log,
                    debug_log=debug_log,
                )
            )
        else:
            chave_boleto = ("BOLETO", origem_boleto)
            if chave_boleto not in avisados:
                log(f"Diretório não encontrado (BOLETO): {origem_boleto}")
                avisados.add(chave_boleto)
            if debug_log:
                debug_log(f"[BOLETO] Diretório não encontrado: {origem_boleto}")

        if time.time() - last_state_reload >= 300:
            atualizar_status("Atualizando estado", "Relendo rascunhos, enviados e relatório...", busy=True)
            nfs_rascunho = _carregar_nfs_rascunho(base_dir, log=log)
            nfs_enviadas = _carregar_nfs_enviadas(base_dir, log=log)
            report_state = _carregar_report_state(base_dir, log=log)
            last_state_reload = time.time()
            if debug_log:
                debug_log("[LOOP] Estado recarregado (rascunhos/enviados/relatorio).")

        if (cfg.get("auto_update_enabled", "1").strip() == "1") and (time.time() - last_update_check >= update_interval):
            last_update_check = time.time()
            atualizar_status("Verificando atualização", "Consultando a versão mais recente...", busy=True)
            if _verificar_atualizacao_github(base_dir, log=log, prompt=False, notify=False):
                log("Atualização iniciada. Encerrando o aplicativo...")
                os._exit(0)

        if eventos:
            atualizar_status("Criando rascunhos", "Compondo NFs prontas para envio...", busy=True)
            _tentar_criar_rascunhos(base_dir, gmail_service, eventos, estado_nf, nfs_rascunho, nfs_enviadas, report_state, log=log)
            _salvar_report_state(base_dir, report_state, log=log)
        elif debug_log:
            debug_log("[LOOP] Nenhum evento gerado neste ciclo.")

        if cache:
            expira = time.time() - cache_ttl
            cache = {k: v for k, v in cache.items() if v >= expira}
        pdf_events = sum(1 for ev in eventos if ev.get("tipo") == "pdf")
        xml_events = sum(1 for ev in eventos if ev.get("tipo") == "xml")
        boleto_events = sum(1 for ev in eventos if ev.get("tipo") == "boleto")
        cycle_seconds = round(time.perf_counter() - cycle_started_at, 3)
        atualizar_status(
            "Aguardando",
            f"Próxima varredura em {intervalo}s.",
            busy=False,
            last_cycle_seconds=cycle_seconds,
            last_cycle_finished_at=datetime.now().isoformat(timespec="seconds"),
            last_events_total=len(eventos),
            last_pdf_events=pdf_events,
            last_xml_events=xml_events,
            last_boleto_events=boleto_events,
        )
        if eventos or cycle_seconds >= 5:
            log(
                f"Ciclo concluído em {cycle_seconds:.2f}s | "
                f"PDF {pdf_events} | XML {xml_events} | BOLETO {boleto_events} | "
                f"próxima varredura em {intervalo}s."
            )

# Lógica da Beatrice Review

def _undo_history_path(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_UNDO_PATH", str(appdata / "PdfWatcher" / "undo_history.json")))

def _carregar_undo_history(base_dir: Path, log=print) -> list:
    path = _undo_history_path(base_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return raw
        except Exception as e:
            log(f"Falha ao ler histórico de undo: {e}")
    return []

def _salvar_undo_history(base_dir: Path, history: list, log=print):
    path = _undo_history_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"Falha ao salvar histórico de undo: {e}")


def _review_duplicates_dir(base_dir: Path) -> Path:
    appdata = Path(os.getenv("APPDATA", str(base_dir)))
    return Path(os.getenv("PDF_REVIEW_DUPLICATES_PATH", str(appdata / "PdfWatcher" / "review_duplicates")))


def _listar_boletos_review(target_folder: Path) -> list[Path]:
    return sorted(
        p for p in target_folder.rglob("*.pdf")
        if p.is_file() and p.name.upper().startswith("BOLETO NF")
    )


def _coletar_duplicatas_review(target_folder: Path) -> list[tuple[Path, Path]]:
    duplicatas: list[tuple[Path, Path]] = []
    for pdf_file in _listar_boletos_review(target_folder):
        texto = _extrair_texto_pdf(pdf_file, log=lambda *a: None)
        info = _extrair_info_boleto_pdf(pdf_file, log=lambda *a: None, texto=texto)
        if not info.get("nosso_numero"):
            continue
        novo_nome = _nomear_boleto(info, pdf_file.name)
        if novo_nome == pdf_file.name:
            continue
        novo_caminho = pdf_file.parent / novo_nome
        if novo_caminho.exists():
            duplicatas.append((pdf_file, novo_caminho))
    return duplicatas


def _gerar_destino_duplicata_review(session_dir: Path, origem: Path) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    destino = session_dir / origem.name
    contador = 2
    while destino.exists():
        destino = session_dir / f"{origem.stem} ({contador}){origem.suffix}"
        contador += 1
    return destino


_review_process = None
_review_window_lock = threading.Lock()

def _abrir_review_em_thread(base_dir: Path, log=print):
    global _review_process
    with _review_window_lock:
        if _review_process and _review_process.poll() is None:
            return
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--review"]
                cwd = str(Path(sys.executable).parent)
            else:
                cmd = [sys.executable, str(Path(__file__).resolve()), "--review"]
                cwd = str(base_dir)
            _review_process = subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            log(f"Falha ao abrir Revisão: {e}")

def _extrair_ano_mes_pasta_review(pasta: Path) -> tuple[int, int]:
    partes = [_normalizar_nome_arquivo(p).upper() for p in pasta.parts]
    meses_mapa = {nome: i + 1 for i, nome in enumerate(MESES)}

    for parte in reversed(partes):
        m = re.fullmatch(r"(0[1-9]|1[0-2])-(20\d{2})", parte)
        if m:
            return int(m.group(2)), int(m.group(1))

    for i in range(len(partes) - 1):
        if re.fullmatch(r"20\d{2}", partes[i]) and partes[i + 1] in meses_mapa:
            return int(partes[i]), meses_mapa[partes[i + 1]]

    return 0, 0


def _listar_pastas_review_boleto(base_dir: Path, log=print) -> list[dict[str, object]]:
    cfg = _carregar_config(base_dir, log=lambda *a: None)
    roots: list[tuple[str, Path]] = []

    for label, key in (("MVA", "boleto_destino_mva"), ("HORIZONTE", "boleto_destino_horizonte")):
        raw = (cfg.get(key) or "").strip()
        if raw:
            roots.append((label, Path(raw)))

    if any(p.is_file() and p.name.upper().startswith("BOLETO NF") for p in base_dir.glob("*.pdf")):
        roots.append(("WORKSPACE", base_dir))

    entries = []
    seen = set()

    for source_label, root in roots:
        if not root.exists():
            continue

        boleto_files = [
            p for p in root.rglob("*.pdf")
            if p.is_file() and p.name.upper().startswith("BOLETO NF")
        ]
        if not boleto_files:
            continue

        grouped: dict[Path, int] = {}
        for pdf_file in boleto_files:
            target_dir = pdf_file.parent
            current = pdf_file.parent
            while True:
                year, month = _extrair_ano_mes_pasta_review(current)
                if year or month:
                    target_dir = current
                    break
                if current == root or current.parent == current:
                    break
                current = current.parent
            grouped[target_dir] = grouped.get(target_dir, 0) + 1

        for folder, count in grouped.items():
            key = str(folder.resolve()) if folder.exists() else str(folder)
            if key in seen:
                continue
            seen.add(key)
            year, month = _extrair_ano_mes_pasta_review(folder)
            try:
                relative = folder.relative_to(root)
                relative_text = str(relative) if str(relative) != "." else "raiz atual"
            except Exception:
                relative_text = folder.name
            relative_text = relative_text.replace("\\", " / ")
            entries.append({
                "source": source_label,
                "path": folder,
                "count": count,
                "year": year,
                "month": month,
                "label": f"{source_label} | {relative_text} | {count} boleto(s)",
            })

    entries.sort(key=lambda item: (item["year"], item["month"], item["count"], item["label"].lower()), reverse=True)
    return entries


def _abrir_review(base_dir: Path, log=print):
    try:
        from PySide6.QtWidgets import (
            QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
            QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout
        )
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QTextCursor
    except Exception as e:
        log(f"PySide6 não encontrado: {e}")
        return

    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication(sys.argv)
        created_app = True

    dialog = QDialog()
    dialog.setWindowTitle("PdfWatcher - Revisão Beatrice")
    dialog.setMinimumSize(920, 620)
    dialog.setStyleSheet("""
        QDialog { background: #2a170f; color: #ffffff; }
        QLabel { color: #ffffff; }
        QLabel#title { font-size: 22px; font-weight: 700; color: #ff9f43; }
        QLabel#subtitle { color: #ffd7b0; }
        QLabel#meta { color: #ffd7b0; }
        QFrame#card {
            background: #3a2418; border: 1px solid #b86a27; border-radius: 12px;
        }
        QComboBox {
            background: #24150d; color: #ffffff; border: 1px solid #b86a27;
            border-radius: 8px; padding: 8px 10px; min-height: 20px;
        }
        QComboBox:hover, QComboBox:focus { border: 1px solid #ff9f43; }
        QPlainTextEdit {
            background: #24150d; color: #ffffff; border: 1px solid #b86a27;
            border-radius: 10px; padding: 10px; font-family: Consolas, monospace;
        }
        QPushButton {
            background: #5a341d; color: #ffffff; border: 1px solid #b86a27;
            border-radius: 8px; padding: 8px 12px; font-weight: 600;
        }
        QPushButton:hover { background: #6a3d21; }
        QPushButton:pressed { background: #4a2b16; }
        QPushButton.primary { background: #ff8a1f; border: 0; }
        QPushButton.primary:hover { background: #ff9f43; }
        QPushButton.warning { background: #8a4b16; border: 0; }
        QPushButton.warning:hover { background: #a85d1b; }
        QPushButton.danger { background: #8c2f1f; border: 0; }
        QPushButton.danger:hover { background: #a83a27; }
        QMessageBox { background: #2a170f; color: #ffffff; }
        QMessageBox QLabel { color: #ffffff; }
        QMessageBox QPushButton {
            background: #ff8a1f; color: #ffffff; border: 0; border-radius: 8px; padding: 6px 12px;
        }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)

    title = QLabel("Revisão Inteligente de Boletos (Beatrice)")
    title.setObjectName("title")
    subtitle = QLabel(
        "Escolha uma pasta da estrutura mês/ano para revisar. "
        "A Beatrice não reprocessa mais tudo automaticamente."
    )
    subtitle.setObjectName("subtitle")
    layout.addWidget(title)
    layout.addWidget(subtitle)

    selector_card = QFrame()
    selector_card.setObjectName("card")
    selector_layout = QVBoxLayout(selector_card)
    selector_layout.setContentsMargins(14, 14, 14, 14)
    selector_layout.setSpacing(8)

    selector_label = QLabel("Pasta para revisar")
    selector_label.setObjectName("meta")
    folder_combo = QComboBox()
    folder_path_label = QLabel()
    folder_path_label.setWordWrap(True)
    folder_path_label.setObjectName("meta")
    folder_info_label = QLabel()
    folder_info_label.setObjectName("meta")

    selector_layout.addWidget(selector_label)
    selector_layout.addWidget(folder_combo)
    selector_layout.addWidget(folder_path_label)
    selector_layout.addWidget(folder_info_label)
    layout.addWidget(selector_card)

    text_log = QPlainTextEdit()
    text_log.setReadOnly(True)
    text_log.setMaximumBlockCount(5000)
    layout.addWidget(text_log, 1)

    class ReviewWorker(QThread):
        log_signal = Signal(str)
        finished_signal = Signal()

        def __init__(self, base_dir: Path, target_folder: Path):
            super().__init__()
            self.base_dir = base_dir
            self.target_folder = target_folder
            self._is_running = True
            self._pause_event = threading.Event()
            self._pause_event.set()

        def stop(self):
            self._is_running = False
            self._pause_event.set()

        def pause(self):
            if self._is_running and self._pause_event.is_set():
                self._pause_event.clear()
                self._log("Revisão pausada. Clique em Continuar para retomar.")

        def resume(self):
            if self._is_running and not self._pause_event.is_set():
                self._pause_event.set()
                self._log("Revisão retomada.")

        def is_paused(self) -> bool:
            return not self._pause_event.is_set()

        def _log(self, msg: str):
            self.log_signal.emit(msg)

        def run(self):
            target_folder = self.target_folder
            if not target_folder.exists():
                self._log(f"ERRO: pasta não encontrada: {target_folder}")
                self.finished_signal.emit()
                return

            arquivos = _listar_boletos_review(target_folder)
            self._log(f"Pasta selecionada: {target_folder}")
            self._log(f"Boletos encontrados: {len(arquivos)}")

            if not arquivos:
                self._log("Nenhum boleto com prefixo 'BOLETO NF' foi encontrado nesta pasta.")
                self.finished_signal.emit()
                return

            history = _carregar_undo_history(self.base_dir, log=lambda *a: None)
            batch = []
            corrigidos = 0
            avisos = 0
            duplicatas_ignoradas = 0

            for pdf_file in arquivos:
                if not self._is_running:
                    self._log("Encerrando a revisão atual...")
                    break
                while self._is_running and self.is_paused():
                    time.sleep(0.1)
                if not self._is_running:
                    self._log("Encerrando a revisão atual...")
                    break

                texto = _extrair_texto_pdf(pdf_file, log=lambda *a: None)
                info = _extrair_info_boleto_pdf(pdf_file, log=lambda *a: None, texto=texto)
                novo_nome = _nomear_boleto(info, pdf_file.name)

                if not info.get("nosso_numero"):
                    avisos += 1
                    self._log(f"AVISO: número do boleto não identificado em {pdf_file.name}")
                    novo_caminho = _encaminhar_boleto_pendente(pdf_file, self.base_dir, info, log=lambda msg: self._log(msg))
                    if novo_caminho and novo_caminho != pdf_file:
                        batch.append({"de": str(novo_caminho), "para": str(pdf_file)})
                        corrigidos += 1
                    continue

                if novo_nome == pdf_file.name:
                    continue

                novo_caminho = pdf_file.parent / novo_nome
                if novo_caminho.exists():
                    duplicatas_ignoradas += 1
                    self._log(f"IGNORADO: destino já existe para {pdf_file.name} -> {novo_nome}")
                    continue

                try:
                    shutil.move(str(pdf_file), str(novo_caminho))
                    batch.append({"de": str(novo_caminho), "para": str(pdf_file)})
                    corrigidos += 1
                    self._log(f"CORRIGIDO: {pdf_file.name} -> {novo_nome}")
                except Exception as e:
                    self._log(f"ERRO: não foi possível mover {pdf_file.name}: {e}")

            if batch:
                history.append({
                    "data_execucao": datetime.now().isoformat(timespec="seconds"),
                    "acoes": batch,
                })
                _salvar_undo_history(self.base_dir, history[-10:], log=lambda *a: None)

            if corrigidos:
                self._log(f"Finalizado. {corrigidos} boleto(s) foram corrigidos.")
            else:
                self._log("Finalizado. Nenhum boleto precisou ser corrigido.")
            if avisos:
                self._log(f"Avisos: {avisos} arquivo(s) ficaram sem número identificado automaticamente.")
            if duplicatas_ignoradas:
                self._log(
                    f"Duplicatas detectadas: {duplicatas_ignoradas} arquivo(s) ficaram na pasta porque o nome correto já existia. "
                    f"Use 'Excluir duplicatas' para limpar esses casos."
                )

            self.finished_signal.emit()

    class DuplicateCleanupWorker(QThread):
        log_signal = Signal(str)
        finished_signal = Signal()

        def __init__(self, base_dir: Path, target_folder: Path):
            super().__init__()
            self.base_dir = base_dir
            self.target_folder = target_folder

        def _log(self, msg: str):
            self.log_signal.emit(msg)

        def run(self):
            target_folder = self.target_folder
            if not target_folder.exists():
                self._log(f"ERRO: pasta não encontrada: {target_folder}")
                self.finished_signal.emit()
                return

            duplicatas = _coletar_duplicatas_review(target_folder)
            self._log(f"Pasta selecionada: {target_folder}")
            self._log(f"Duplicatas encontradas: {len(duplicatas)}")

            if not duplicatas:
                self._log("Nenhuma duplicata elegível para exclusão foi encontrada nesta pasta.")
                self.finished_signal.emit()
                return

            history = _carregar_undo_history(self.base_dir, log=lambda *a: None)
            batch = []
            session_dir = _review_duplicates_dir(self.base_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
            removidas = 0

            for pdf_file, novo_caminho in duplicatas:
                destino_lixeira = _gerar_destino_duplicata_review(session_dir, pdf_file)
                try:
                    shutil.move(str(pdf_file), str(destino_lixeira))
                    batch.append({"de": str(destino_lixeira), "para": str(pdf_file)})
                    removidas += 1
                    self._log(
                        f"EXCLUÍDA DUPLICATA: {pdf_file.name} | mantido: {novo_caminho.name}"
                    )
                except Exception as e:
                    self._log(f"ERRO: não foi possível excluir a duplicata {pdf_file.name}: {e}")

            if batch:
                history.append({
                    "data_execucao": datetime.now().isoformat(timespec="seconds"),
                    "acoes": batch,
                })
                _salvar_undo_history(self.base_dir, history[-10:], log=lambda *a: None)

            if removidas:
                self._log(
                    f"Limpeza concluída. {removidas} duplicata(s) foram removidas da pasta e podem ser restauradas em 'Desfazer última revisão'."
                )
            else:
                self._log("Limpeza concluída. Nenhuma duplicata foi removida.")

            self.finished_signal.emit()

    class UndoWorker(QThread):
        log_signal = Signal(str)
        finished_signal = Signal()

        def __init__(self, base_dir: Path):
            super().__init__()
            self.base_dir = base_dir

        def _log(self, msg: str):
            self.log_signal.emit(msg)

        def run(self):
            history = _carregar_undo_history(self.base_dir, log=lambda *a: None)
            if not history:
                self._log("Nenhum histórico para desfazer.")
                self.finished_signal.emit()
                return

            last_batch = history.pop()
            acoes = last_batch.get("acoes", [])
            self._log(f"Desfazendo lote de {last_batch.get('data_execucao')} com {len(acoes)} ação(ões)...")

            sucessos = 0
            for acao in acoes:
                de = Path(acao["de"])
                para = Path(acao["para"])
                if de.exists() and not para.exists():
                    try:
                        shutil.move(str(de), str(para))
                        self._log(f"DESFEITO: {de.name} voltou para {para.name}")
                        sucessos += 1
                    except Exception as e:
                        self._log(f"ERRO: falha ao desfazer {de.name}: {e}")
                else:
                    self._log(f"IGNORADO: {de.name} não existe ou o destino já está ocupado.")

            _salvar_undo_history(self.base_dir, history, log=lambda *a: None)
            self._log(f"Undo finalizado. {sucessos} ação(ões) revertidas.")
            self.finished_signal.emit()

    worker = None
    folder_entries: list[dict[str, object]] = []

    def append_log(texto: str):
        text_log.appendPlainText(texto)
        text_log.moveCursor(QTextCursor.End)

    def current_entry() -> dict[str, object] | None:
        idx = folder_combo.currentIndex()
        if idx < 0 or idx >= len(folder_entries):
            return None
        return folder_entries[idx]

    def refresh_folder_details():
        entry = current_entry()
        has_entry = entry is not None
        if not has_entry:
            folder_path_label.setText("Nenhuma pasta de boletos encontrada na estrutura configurada.")
            folder_info_label.setText("Revise a configuração ou coloque os arquivos na pasta de destino correta.")
            sync_controls()
            return
        folder_path_label.setText(f"Pasta: {entry['path']}")
        folder_info_label.setText(
            f"Origem: {entry['source']} | Boletos detectados: {entry['count']}"
        )
        sync_controls()

    def reload_folders(preferred_path: str | None = None):
        nonlocal folder_entries
        folder_entries = _listar_pastas_review_boleto(base_dir, log=log)
        folder_combo.blockSignals(True)
        folder_combo.clear()
        if folder_entries:
            for entry in folder_entries:
                folder_combo.addItem(entry['label'])
            idx = 0
            if preferred_path:
                for i, entry in enumerate(folder_entries):
                    if str(entry['path']) == preferred_path:
                        idx = i
                        break
            folder_combo.setCurrentIndex(idx)
        else:
            folder_combo.addItem("Nenhuma pasta disponível")
        folder_combo.blockSignals(False)
        refresh_folder_details()

    def sync_controls():
        review_running = bool(worker and isinstance(worker, ReviewWorker) and worker.isRunning())
        busy = bool(worker and worker.isRunning())
        has_entry = current_entry() is not None

        folder_combo.setEnabled((not busy) and bool(folder_entries))
        btn_refresh.setEnabled(not busy)
        btn_start.setEnabled((not busy) and has_entry)
        btn_delete_duplicates.setEnabled((not busy) and has_entry)
        btn_undo.setEnabled(not busy)
        btn_pause.setEnabled(review_running)
        btn_pause.setText("Continuar" if review_running and worker.is_paused() else "Pausar")
        btn_close.setEnabled(not busy)

    def on_start():
        nonlocal worker
        entry = current_entry()
        if entry is None:
            QMessageBox.warning(dialog, "Revisão", "Selecione uma pasta válida para revisar.")
            return

        text_log.clear()
        worker = ReviewWorker(base_dir, Path(entry['path']))
        worker.log_signal.connect(append_log)

        def on_finished():
            nonlocal worker
            worker = None
            reload_folders(str(entry['path']))

        worker.finished_signal.connect(on_finished)
        sync_controls()
        worker.start()

    def on_undo():
        nonlocal worker
        text_log.clear()
        worker = UndoWorker(base_dir)
        worker.log_signal.connect(append_log)

        def on_finished():
            nonlocal worker
            preferred = str(current_entry()['path']) if current_entry() else None
            worker = None
            reload_folders(preferred)

        worker.finished_signal.connect(on_finished)
        sync_controls()
        worker.start()

    def on_delete_duplicates():
        nonlocal worker
        entry = current_entry()
        if entry is None:
            QMessageBox.warning(dialog, "Duplicatas", "Selecione uma pasta válida para limpar.")
            return

        resposta = QMessageBox.question(
            dialog,
            "Excluir duplicatas",
            (
                "A Beatrice vai remover da pasta revisada os boletos cujo nome corrigido já existe.\n"
                "Os arquivos removidos poderão ser restaurados em 'Desfazer última revisão'.\n\n"
                "Deseja continuar?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return

        text_log.clear()
        worker = DuplicateCleanupWorker(base_dir, Path(entry['path']))
        worker.log_signal.connect(append_log)

        def on_finished():
            nonlocal worker
            worker = None
            reload_folders(str(entry['path']))

        worker.finished_signal.connect(on_finished)
        sync_controls()
        worker.start()

    def on_pause_toggle():
        if worker and isinstance(worker, ReviewWorker) and worker.isRunning():
            if worker.is_paused():
                worker.resume()
            else:
                worker.pause()
            sync_controls()

    actions = QHBoxLayout()
    btn_start = QPushButton("Iniciar revisão")
    btn_start.setProperty("class", "primary")
    btn_refresh = QPushButton("Atualizar lista")
    btn_delete_duplicates = QPushButton("Excluir duplicatas")
    btn_delete_duplicates.setProperty("class", "danger")
    btn_undo = QPushButton("Desfazer última revisão")
    btn_undo.setProperty("class", "warning")
    btn_pause = QPushButton("Pausar")
    btn_pause.setProperty("class", "warning")
    btn_close = QPushButton("Fechar")

    btn_start.clicked.connect(on_start)
    btn_refresh.clicked.connect(lambda: reload_folders(str(current_entry()['path']) if current_entry() else None))
    btn_delete_duplicates.clicked.connect(on_delete_duplicates)
    btn_undo.clicked.connect(on_undo)
    btn_pause.clicked.connect(on_pause_toggle)
    btn_close.clicked.connect(dialog.reject)
    folder_combo.currentIndexChanged.connect(refresh_folder_details)

    actions.addWidget(btn_start)
    actions.addWidget(btn_refresh)
    actions.addWidget(btn_delete_duplicates)
    actions.addWidget(btn_undo)
    actions.addWidget(btn_pause)
    actions.addStretch(1)
    actions.addWidget(btn_close)
    layout.addLayout(actions)

    reload_folders()
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    dialog.exec()

    if worker and worker.isRunning() and isinstance(worker, ReviewWorker):
        worker.stop()
        worker.wait(3000)

    if created_app:
        app.quit()


def _run_tray():
    try:
        import pystray
    except Exception:
        print("pystray nao encontrado. Instale com: pip install pystray pillow")
        return

    stop_event = threading.Event()
    thread = threading.Thread(target=_run_loop, args=(stop_event, None), daemon=True)
    thread.start()
    base_dir = _base_dir()

    def on_config(icon, item):
        _abrir_interface_config_em_thread(base_dir, log=print)

    def on_logs(icon, item):
        _abrir_visualizador_logs_em_thread(base_dir, log=print)

    def on_status(icon, item):
        _abrir_status_em_thread(base_dir, log=print)

    def on_update(icon, item):
        _verificar_atualizacao_em_thread(base_dir, log=print)

    def on_review(icon, item):
        _abrir_review_em_thread(base_dir, log=print)

    def on_quit(icon, item):
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Configurar pastas", on_config),
        pystray.MenuItem("Revisão de Boletos (Beatrice)", on_review),
        pystray.MenuItem("Status", on_status),
        pystray.MenuItem("Ver logs", on_logs),
        pystray.MenuItem("Verificar atualização", on_update),
        pystray.MenuItem("Sair", on_quit),
    )
    icon = pystray.Icon("PdfWatcher", _criar_icone_tray(), "PdfWatcher", menu)
    icon.run()

def _single_instance_guard() -> bool:
    try:
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}_MUTEX")
        if ctypes.windll.kernel32.GetLastError() == 183:
            return False
        return True
    except Exception:
        return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tray", action="store_true", help="Roda no console, sem tray.")
    parser.add_argument("--config", action="store_true", help="Abre a interface de Configuração e sai.")
    parser.add_argument("--logs", action="store_true", help="Abre o visualizador de logs e sai.")
    parser.add_argument("--status", action="store_true", help="Abre a janela de status e sai.")
    parser.add_argument("--review", action="store_true", help="Abre a interface de revisão de boletos.")
    parser.add_argument("--check-update", action="store_true", help="Abre a verificação manual de atualização e sai.")
    args = parser.parse_args()
    base_dir = _base_dir()

    if not args.config and not args.logs and not args.status and not args.check_update and not args.review:
        if not _single_instance_guard():
            try:
                from PySide6.QtWidgets import QMessageBox, QApplication
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.information(None, "PdfWatcher", "O aplicativo já está aberto.")
            except Exception:
                pass
            return

    if args.config:
        _garantir_arquivos_iniciais(base_dir, log=print)
        _abrir_interface_config(base_dir, log=print)
    elif args.logs:
        _garantir_arquivos_iniciais(base_dir, log=print)
        _abrir_visualizador_logs(base_dir, log=print)
    elif args.status:
        _garantir_arquivos_iniciais(base_dir, log=print)
        _abrir_status(base_dir, log=print)
    elif args.review:
        _garantir_arquivos_iniciais(base_dir, log=print)
        _abrir_review(base_dir, log=print)
    elif args.check_update:
        _garantir_arquivos_iniciais(base_dir, log=print)
        _verificar_atualizacao_manual(base_dir, log=print)
    elif args.no_tray:
        _fluxo_primeira_execucao(base_dir, log=print)
        _garantir_arquivos_iniciais(base_dir, log=print)
        stop_event = threading.Event()
        try:
            _run_loop(stop_event, None)
        except KeyboardInterrupt:
            stop_event.set()
    else:
        _fluxo_primeira_execucao(base_dir, log=print)
        _garantir_arquivos_iniciais(base_dir, log=print)
        _run_tray()

if __name__ == "__main__":
    main()
