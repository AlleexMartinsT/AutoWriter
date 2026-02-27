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
APP_VERSION = "1.1.4"
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


def _carregar_config(base_dir: Path, log=print) -> dict[str, str]:
    cfg = _default_paths(base_dir)
    path = _config_path(base_dir)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
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


def _arquivo_estavel(caminho: Path, intervalo: int = 1, tentativas: int = 3) -> bool:
    try:
        if not caminho.exists():
            return False
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
    if re.search(r"\b(ENDERECO|MUNICIPIO UF CEP|NUMERO DO DOCUMENTO|DADOS DO PAGADOR|FICHA DE COMPENSACAO|LOCAL DE PAGAMENTO|COOPERATIVA CONTRATANTE|AUTENTICACAO MECANICA)\b", u):
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


def _extrair_info_boleto_pdf(caminho: Path, log=print) -> dict[str, str | None]:
    texto = _extrair_texto_pdf(caminho, log=log) or ""
    if not texto.strip():
        return {
            "nf": _extrair_nf_do_nome(caminho.name),
            "pagador": None,
            "nosso_numero": None,
            "beneficiario": None,
            "beneficiario_cnpj": None,
        }

    m_nf = re.search(r"\bNF\s*0*([0-9]{1,12})\b", texto, re.IGNORECASE)
    nf = m_nf.group(1).lstrip("0") if m_nf else None
    if not nf:
        m_nrdoc = re.search(r"Nr\.\s*do documento.*?\n\s*([0-9]{1,12})\b", texto, re.IGNORECASE | re.DOTALL)
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
                nome = cnpj_re.split(nome)[0].strip()
            nome = re.sub(r"\s*-\s*CNPJ.*$", "", nome, flags=re.IGNORECASE).strip()
            nome = re.sub(r"\s+CNPJ[:\s].*$", "", nome, flags=re.IGNORECASE).strip()
            return nome

        # 1) Procurar bloco "Pagador" e usar a primeira linha útil abaixo dele.
        for i, ln in enumerate(linhas):
            if not ln:
                continue
            if any(re.search(rx, ln, re.IGNORECASE) for rx in labels_pagador):
                m = re.search(r"PAGADOR\s*[:\-]\s*(.+)$", ln, re.IGNORECASE)
                if m:
                    nome = _limpar_nome_linha(m.group(1))
                    if nome and nome.upper() not in blacklist and not _nome_boleto_parece_invalido(nome):
                        return nome
                for j in range(i + 1, min(i + 8, len(linhas))):
                    cand = linhas[j].strip()
                    if not cand:
                        continue
                    if cand.upper() in blacklist:
                        continue
                    if re.search(r"benefici[aá]rio|cedente|sacador|avalista", cand, re.IGNORECASE):
                        break
                    nome = _limpar_nome_linha(cand)
                    if nome and not _nome_boleto_parece_invalido(nome):
                        return nome

        # 2) Fallback: linha que contenha CNPJ e pareça nome do pagador.
        for ln in linhas:
            if not ln or not cnpj_re.search(ln):
                continue
            if _linha_digitavel_boleto(ln):
                continue
            if re.search(r"benefici[aá]rio|cedente|sacador|avalista|ag[êe]ncia/c[oó]digo|nosso n[uú]mero", ln, re.IGNORECASE):
                continue
            nome = _limpar_nome_linha(ln)
            if nome and nome.upper() not in blacklist and not _nome_boleto_parece_invalido(nome):
                return nome
        return None

    def _extrair_beneficiario(txt: str) -> str | None:
        linhas = [ln.strip() for ln in txt.splitlines()]
        texto_mva = os.getenv("BOLETO_TEXT_MATCH_MVA", "MVA").strip()
        texto_horizonte = os.getenv("BOLETO_TEXT_MATCH_HORIZONTE", "HORIZONTE").strip()

        def _contem_termo_esperado(ln: str, termo: str) -> bool:
            if not termo:
                return False
            return _texto_compacto(termo) in _texto_compacto(ln)

        # 1) Prioriza linhas que contenham o nome esperado (MVA/HORIZONTE)
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
            "INSTRUÇÕES (TEXTO DE RESPONSABILIDADE DO BENEFICIÁRIO)",
            "PAGADOR",
            "BENEFICIÁRIO FINAL",
            "FICHA DE COMPENSAÇÃO",
            "VENCIMENTO",
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

        # 2) Procurar bloco de beneficiário.
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

    m_nosso = re.search(r"Nosso\s*n[uú]mero[\s\S]{0,120}?([0-9]{6,})", texto, re.IGNORECASE)
    nosso_numero = m_nosso.group(1) if m_nosso else None
    if not nosso_numero:
        linhas = [ln.strip() for ln in texto.splitlines()]
        for i, ln in enumerate(linhas):
            if re.search(r"Nosso\s*n[uú]mero", ln, re.IGNORECASE):
                janela = " ".join(linhas[i:i+5])
                m_alt = re.search(r"\b(\d{4,}-?\d{0,2})\b", janela)
                if m_alt:
                    nosso_numero = m_alt.group(1)
                break
    if not nosso_numero:
        linhas = [ln.strip() for ln in texto.splitlines()]
        for ln in linhas:
            if nf and nf in ln and re.search(r"\bDM\b|\bN\b", ln):
                m_alt = re.search(r"\b(\d{4,}-\d)\b", ln)
                if m_alt:
                    nosso_numero = m_alt.group(1)
                    break
    if not nosso_numero:
        m_alt = re.findall(r"\b(\d{4,}-\d)\b", texto)
        if m_alt:
            nosso_numero = m_alt[-1]

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
        # Mantém o formato completo em boletos com hífen (ex.: 7239-1).
        if "-" not in final_nosso or len(final_nosso) > 10:
            final_nosso = final_nosso[-4:] if len(final_nosso) >= 4 else final_nosso
    sufixo = f" BLT {final_nosso}" if final_nosso else ""
    return f"BOLETO NF{nf} {pagador_curto}{sufixo}.pdf"


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


def _montar_corpo_email(base_dir: Path, nf: str) -> str:
    path = _template_path(base_dir)
    if path.exists():
        txt = path.read_text(encoding="utf-8", errors="ignore")
    else:
        txt = "Boa tarde!!!\n\nSegue em anexo XML PDF NF{NF} + BOLETO\n\n***Favor confirmar e-mail***\nAtt"
    txt = re.sub(r"NF\s*\d+", f"NF{nf}", txt, flags=re.IGNORECASE)
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
        texto = None
        if texto_mva or texto_horizonte:
            texto = _extrair_texto_pdf(caminho, log=log)
            if not texto:
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

        info_boleto = _extrair_info_boleto_pdf(caminho, log=log)
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
        if pagador and texto_mva and _texto_compacto(texto_mva) in _texto_compacto(pagador):
            erros_extracao.append("pagador_com_nome_mva")
        if pagador and texto_horizonte and _texto_compacto(texto_horizonte) in _texto_compacto(pagador):
            erros_extracao.append("pagador_com_nome_horizonte")
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

    def pasta_mes_atual(base: Path) -> Path:
        hoje = datetime.now()
        return base / hoje.strftime("%Y") / MESES[hoje.month - 1]

    for base in destinos_pdf:
        pasta = pasta_mes_atual(base)
        if not pasta.exists():
            continue
        for p in pasta.glob("*.pdf"):
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
        pasta = pasta_mes_atual(base)
        if not pasta.exists():
            continue
        for p in pasta.glob("*.xml"):
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
            QTextEdit,
            QTabWidget,
            QWidget,
            QCheckBox,
        )
        from PySide6.QtCore import Qt, QTimer
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
    text_main = QTextEdit()
    text_main.setReadOnly(True)
    text_debug = QTextEdit()
    text_debug.setReadOnly(True)
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
    btn_open = QPushButton("Abrir arquivo")
    btn_report = QPushButton("Relatório")
    btn_open.setProperty("class", "secondary")
    btn_close = QPushButton("Fechar")
    btn_close.setProperty("class", "secondary")
    actions.addWidget(btn_refresh)
    actions.addWidget(btn_open)
    actions.addWidget(btn_report)
    actions.addStretch(1)
    actions.addWidget(btn_close)
    layout.addLayout(actions)

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

    def carregar_log(path: Path, widget: QTextEdit):
        if not path.exists():
            widget.setPlainText("O log ainda não foi criado.")
            return
        try:
            bar = widget.verticalScrollBar()
            at_bottom = bar.value() >= (bar.maximum() - 5)
            prev_value = bar.value()
            conteudo = path.read_text(encoding="utf-8", errors="ignore")
            exibicao = _formatar_log(conteudo[-200000:])  # limita exibicao para desempenho
            widget.setPlainText(exibicao)
            if chk_auto_scroll.isChecked() and at_bottom:
                widget.moveCursor(QTextCursor.End)
            else:
                bar.setValue(prev_value)
        except Exception as e:
            widget.setPlainText(f"Falha ao ler o log: {e}")

    def carregar_ativos():
        carregar_log(caminho_log, text_main)
        carregar_log(caminho_debug, text_debug)

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

    timer = QTimer(dialog)
    timer.setInterval(2000)
    timer.timeout.connect(carregar_ativos)
    timer.start()

    def atualizar_timer():
        if chk_pause_refresh.isChecked():
            timer.stop()
        else:
            if not timer.isActive():
                timer.start()
        carregar_ativos()

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
            elif clicked == btn_debug:
                path = caminho_debug
            elif clicked == btn_report:
                path = _report_path(base_dir)
            else:
                return
        except Exception:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except Exception as e:
            log(f"Falha ao limpar log: {e}")
        carregar_ativos()

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

    btn_refresh.clicked.connect(carregar_ativos)
    btn_open.clicked.connect(abrir_arquivo)
    btn_report.clicked.connect(lambda: _abrir_relatorio(base_dir, log=log))
    btn_close.clicked.connect(dialog.close)
    chk_show_dates.stateChanged.connect(lambda *_: (salvar_viewer(), carregar_ativos()))
    chk_show_time.stateChanged.connect(lambda *_: (salvar_viewer(), carregar_ativos()))
    chk_auto_scroll.stateChanged.connect(lambda *_: (salvar_viewer(), carregar_ativos()))
    chk_pause_refresh.stateChanged.connect(lambda *_: (salvar_viewer(), atualizar_timer()))
    btn_clear.clicked.connect(limpar_log)
    dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
    carregar_ativos()
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
    except Exception as e:
        log(f"Falha ao preparar arquivos iniciais: {e}")
    return first_run


def _parse_version(tag: str) -> tuple[int, int, int]:
    tag = (tag or "").strip().lstrip("vV")
    parts = tag.split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int(re.sub(r"[^0-9]", "", p)))
        except Exception:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _verificar_atualizacao_github(base_dir: Path, log=print, prompt=True) -> bool:
    repo = GITHUB_REPO
    if not getattr(sys, "frozen", False):
        log("Atualização automática só funciona no executável (modo frozen).")
        return False
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PdfWatcher"})
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log(f"Falha ao verificar atualização: {e}")
        return False

    tag = data.get("tag_name") or data.get("name") or ""
    latest = _parse_version(tag)
    current = _parse_version(APP_VERSION)
    if latest <= current:
        log(f"Atualização: você já está na versão {APP_VERSION}.")
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
        log("Atualização encontrada, mas nenhum .exe foi encontrado nos arquivos do release.")
        return False

    if prompt:
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
        bat = temp_dir / f"PdfWatcher_update_{pid}.bat"
        bat.write_text(
            "\n".join([
                "@echo off",
                f"set PID={pid}",
                f"set OLD_EXE={exe_atual}",
                f"set NEW_EXE={destino}",
                "timeout /t 2 /nobreak >nul",
                ":wait",
                "tasklist /FI \"PID eq %PID%\" | find \"%PID%\" >nul",
                "if %errorlevel%==0 (timeout /t 1 >nul & goto wait)",
                "move /Y \"%NEW_EXE%\" \"%OLD_EXE%\"",
                "start \"\" \"%OLD_EXE%\"",
                "del \"%~f0\"",
            ]),
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", "start", "", str(bat)], shell=False)
        return True
    except Exception as e:
        log(f"Falha ao baixar atualização: {e}")
        return False


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
        "Deseja ativar a criacao de rascunhos de e-mail agora?",
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

    while not stop_event.is_set():
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
            eventos.extend(
                _coletar_eventos_existentes_mes_atual(
                    [destino_mva, destino_horizonte],
                    [destinos_xml["MVA"], destinos_xml["HORIZONTE"]],
                    [destino_boleto_mva, destino_boleto_horizonte],
                    log=log,
                )
            )

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

        if origem_xml.exists():
            eventos.extend(processar_xmls(origem_xml, destinos_xml, cnpj_mva, cnpj_horizonte, cache, log=log, debug_log=debug_log))
        else:
            chave_xml = ("XML", origem_xml)
            if chave_xml not in avisados:
                log(f"Diretório não encontrado (XML): {origem_xml}")
                avisados.add(chave_xml)
            if debug_log:
                debug_log(f"[XML] Diretório não encontrado: {origem_xml}")

        if origem_boleto.exists():
            eventos.extend(
                processar_boletos(
                    origem_boleto,
                    destino_boleto_mva,
                    destino_boleto_horizonte,
                    cnpj_mva,
                    cnpj_horizonte,
                    cache,
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
            nfs_rascunho = _carregar_nfs_rascunho(base_dir, log=log)
            nfs_enviadas = _carregar_nfs_enviadas(base_dir, log=log)
            report_state = _carregar_report_state(base_dir, log=log)
            last_state_reload = time.time()
            if debug_log:
                debug_log("[LOOP] Estado recarregado (rascunhos/enviados/relatorio).")

        if (cfg.get("auto_update_enabled", "1").strip() == "1") and (time.time() - last_update_check >= update_interval):
            last_update_check = time.time()
            if _verificar_atualizacao_github(base_dir, log=log, prompt=True):
                log("Atualização iniciada. Encerrando o aplicativo...")
                stop_event.set()
                return

        if eventos:
            _tentar_criar_rascunhos(base_dir, gmail_service, eventos, estado_nf, nfs_rascunho, nfs_enviadas, report_state, log=log)
            _salvar_report_state(base_dir, report_state, log=log)
        elif debug_log:
            debug_log("[LOOP] Nenhum evento gerado neste ciclo.")

        if cache:
            expira = time.time() - cache_ttl
            cache = {k: v for k, v in cache.items() if v >= expira}
        stop_event.wait(intervalo)


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

    def on_update(icon, item):
        _verificar_atualizacao_github(base_dir, log=print)

    def on_quit(icon, item):
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Configurar pastas", on_config),
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
    args = parser.parse_args()
    base_dir = _base_dir()

    if not args.config and not args.logs:
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
