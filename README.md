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
- A autenticação do Gmail usa `credentials.json` embutido no aplicativo; o usuário só precisa autenticar ou reautenticar a conta quando necessário.

## Melhorias recentes

- A tela de configuração agora possui botão para autenticar ou reautenticar o Gmail manualmente, sem seleção manual de `credentials.json`.
- Antes de criar rascunho, o Gmail agora é consultado pelo número da NF nos e-mails enviados; se já houver envio, a NF é marcada como enviada e rascunhos correspondentes são removidos.
- NFs pagas à vista por indicador de pagamento imediato, cartão, PIX e outros meios sem boleto deixam de exigir boleto nas Pendências, mas não geram mais rascunho automático; o Gmail continua restrito a `PDF + XML + BOLETO`.
- A detecção de NF `à vista` também considera a própria natureza da operação do XML quando o emissor envia combinações incompletas de pagamento, como `tPag=05`, `tPag=90` ou `<pag></pag>`, sem confundir notas marcadas como `a prazo`.
- Rascunhos do Gmail sem assunto ou com mais de 5 dias no rascunho também são removidos pela limpeza automática.
- A integração Gmail passa a tentar reconectar e reprocessar pendências automaticamente, sem depender de desligar e ligar o aplicativo.
- A autenticação Gmail agora tenta abrir o navegador com fallback explícito e, se a abertura automática falhar, exibe e copia o link de autorização.
- Adicionada leitura direta de "nosso número" para boletos vindos do Sicoob ou ZWeb por reconhecimento da assinatura do arquivo CNPJ-BOLETO-ID.pdf.
- Arquivos antigos não esperam mais vários segundos para serem considerados estáveis.
- O fluxo de `PDF` deixou de tentar tratar boleto como PDF comum.
- O fluxo de `BOLETO` deixou de poluir o log com PDFs que não são boleto.
- Foi adicionada uma janela de `Status` com:
  - etapa atual
  - arquivo e pasta em análise
  - progresso finito do ciclo atual
  - detalhe do que está sendo analisado
  - duração do último ciclo
  - intervalo até a próxima varredura
  - contagem de eventos `PDF/XML/BOLETO`
- A janela de logs possui busca compacta sobreposta individualmente em `Log principal` e `Log técnico`, com destaque funcional e navegação por `Enter`, próximo e anterior.
- A tela de `Configurar pastas` agora pode ser redimensionada e usa rolagem quando a altura da tela não comporta todos os campos.
- Apenas os dois caminhos legados exatos de MVA que saíram errados em versões anteriores, `Z:\CAIXA\PDF VENDAS 2026` e `Z:\CAIXA\XML VENDAS 2026`, são ajustados automaticamente para a estrutura real da rede quando necessário.
- Quando houver Pendências, um botão de alerta vermelho pisca no canto superior direito das abas; ao clicar nele, um menu mostra por NF quais itens `PDF/XML/BOLETO` ainda faltam e é atualizado a cada ciclo enquanto o usuário corrige os arquivos.
- A varredura de arquivos já arquivados passou a olhar somente as pastas do mês atual e, após a carga inicial, reler apenas itens novos ou alterados.
- Pendências também são conciliadas com o Gmail enviado para evitar falso alerta em NF já enviada sem trio completo local.
- NFs de devolução agora são ignoradas pelo XML e pelo PDF, deixam de entrar em `Pendências` e também saem do estado local de rascunhos/relatório herdado de versões anteriores.
- A verificação de trio e de pendências agora considera apenas as 50 NFs numericamente mais altas de cada empresa, evitando alertas de semanas atrás.
- Os logs principal e técnico são compactados automaticamente: linhas antigas são removidas e mensagens repetidas são filtradas.
- Arquivos internos de estado agora são gravados com temporário único, retentativas e fallback para reduzir erro de `Acesso negado` no Windows quando há concorrência entre janelas/processos.
- A verificação manual de atualização passou a abrir em subprocesso próprio, para evitar popup “travado”.

## Como o ciclo funciona

O loop principal faz isto:

1. Lê a configuração atual.
2. Analisa a pasta de PDFs.
3. Analisa a pasta de XMLs.
4. Analisa a pasta de boletos.
5. Tenta montar trios por NF para criar rascunhos.
6. Reprocessa pendências de Gmail e remove rascunhos de NFs já enviadas.
7. Aguarda o próximo ciclo.

Por padrão, o próximo ciclo começa após `2` segundos. Esse valor pode ser alterado em `Configurar pastas`, no campo `Repouso entre ciclos`. A variável de ambiente `PDF_POLL_INTERVAL` ainda pode sobrescrever esse valor quando definida.

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
- `PDF_EXISTING_SCAN_INTERVAL`
- `PDF_STABLE_AGE_SECONDS`
- `PDF_LOG_RETENTION_DAYS`
- `GMAIL_RETRY_INTERVAL`
- `GMAIL_PENDING_RETRY_INTERVAL`
- `GMAIL_SENT_RECONCILE_INTERVAL`
- `GMAIL_CLEANUP_INTERVAL`
- `GMAIL_DRAFT_MAX_AGE_DAYS`
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
