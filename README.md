# PdfWatcher

Aplicativo desktop para Windows que monitora pastas de PDF, XML e boleto, move os arquivos para os destinos corretos de cada empresa e, quando o trio da mesma NF está completo, cria rascunhos de e-mail no Gmail.

## O que o programa faz

- Monitora pastas de origem separadas para `PDF`, `XML` e `BOLETO`.
- Move arquivos para `MVA` ou `HORIZONTE`.
- Renomeia XMLs pela chave/Id interno do próprio XML quando disponível.
- Organiza os destinos por data:
  - `PDF/XML`: `ANO\MÊS`
  - `BOLETO`: `MM-AAAA`
- Mantém logs, relatório e estado persistidos em `%APPDATA%\PdfWatcher`.
- Pode criar rascunhos de e-mail quando encontra `PDF + XML + BOLETO` da mesma NF.
- Possui ícone na bandeja, janela de logs, janela de status e atualização automática/manual via GitHub Releases.
- A autenticação do Gmail usa `credentials.json` externo ao lado do aplicativo, sem embutir esse arquivo no executável.

## Melhorias recentes

- A tela de configuração agora possui botão para autenticar ou reautenticar o Gmail manualmente.
- Adicionada leitura direta de "nosso número" para boletos vindos do Sicoob ou ZWeb por reconhecimento da assinatura do arquivo CNPJ-BOLETO-ID.pdf.
- Arquivos antigos não esperam mais vários segundos para serem considerados estáveis.
- O fluxo de `PDF` deixou de tentar tratar boleto como PDF comum.
- O fluxo de `BOLETO` deixou de poluir o log com PDFs que não são boleto.
- Foi adicionada uma janela de `Status` com:
  - etapa atual
  - detalhe do que está sendo analisado
  - duração do último ciclo
  - intervalo até a próxima varredura
  - contagem de eventos `PDF/XML/BOLETO`
- A verificação manual de atualização passou a abrir em subprocesso próprio, para evitar popup “travado”.

## Como o ciclo funciona

O loop principal faz isto:

1. Lê a configuração atual.
2. Analisa a pasta de PDFs.
3. Analisa a pasta de XMLs.
4. Analisa a pasta de boletos.
5. Tenta montar trios por NF para criar rascunhos.
6. Aguarda o próximo ciclo.

Por padrão, o próximo ciclo começa após `2` segundos. Esse valor pode ser alterado pela variável de ambiente `PDF_POLL_INTERVAL`.

## Requisitos

- Windows
- Python 3.13 64-bit

## Instalação

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Como executar

- Aplicativo normal, com ícone na bandeja:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py
```

- Apenas no console:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --no-tray
```

- Apenas a tela de configuração:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --config
```

- Apenas a tela de logs:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --logs
```

- Apenas a tela de status:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --status
```

- Apenas a tela de revisao Beatrice:

```powershell
.\.venv\Scripts\python downloads_pdf_mover.py --review
```

## Revisao Beatrice

- Permite escolher uma pasta da estrutura mes/ano antes de revisar os boletos.
- Pode corrigir nomes antigos com a mesma logica usada no fluxo normal do aplicativo.
- Pode pausar e continuar a revisao sem encerrar o processo.
- Pode excluir duplicatas quando o nome corrigido ja existe na mesma pasta.
- A opcao `Desfazer ultima revisao` tambem restaura duplicatas removidas por essa limpeza.

## Menu da bandeja

O ícone da bandeja oferece:

- `Configurar pastas`
- `Revisao de Boletos (Beatrice)`
- `Status`
- `Ver logs`
- `Verificar atualização`
- `Sair`

## Onde ficam os arquivos de trabalho

Por padrão:

- Configuração: `%APPDATA%\PdfWatcher\config.json`
- Status: `%APPDATA%\PdfWatcher\status.json`
- Log principal: `%APPDATA%\PdfWatcher\logs\watcher.log`
- Log técnico: `%APPDATA%\PdfWatcher\logs\watcher_debug.log`
- Relatório: `%APPDATA%\PdfWatcher\logs\report.txt`

## Variáveis de ambiente úteis

- `PDF_NOME`
- `PDF_PATTERN`
- `PDF_TEXT_MATCH_MVA`
- `PDF_TEXT_MATCH_HORIZONTE`
- `XML_CNPJ_MVA`
- `XML_CNPJ_HORIZONTE`
- `PDF_ALLOW_ALL`
- `PDF_POLL_INTERVAL`
- `PDF_CACHE_TTL`
- `PDF_STABLE_AGE_SECONDS`
- `PDF_LOG_PATH`
- `PDF_DEBUG_LOG_PATH`
- `PDF_REPORT_PATH`
- `PDF_REPORT_STATE_PATH`
- `PDF_STATUS_PATH`
- `UPDATE_CHECK_INTERVAL`

## Build do executável

```powershell
.\.venv\Scripts\python -m PyInstaller PdfWatcher.spec
```

Saída esperada:

- `dist\PdfWatcher.exe`

## Arquivos principais

- `downloads_pdf_mover.py`: aplicação principal, monitoramento, UI e integração.
- `PdfWatcher.spec`: build do executável.
- `requirements.txt`: dependências do projeto.
