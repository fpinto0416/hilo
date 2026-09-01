# CLAUDE.md — hilo

Orientação rápida pra qualquer sessão do Claude Code que abrir este repo.
Detalhes completos ficam no `README.md` — leia ele antes de qualquer
mudança maior.

## O que é

Sinal diário de tendência (HiLo Activator — média móvel do high/low,
janela por ativo) pra ~30 tickers B3. `projeto_hilo.py` calcula o HiLo do
dia, detecta troca de posição, envia Compra/Venda no Telegram e acumula
`historico_ordens.xlsx` (uma linha por troca de posição, não por dia —
diferente do ledger diário do api_OMQS que grava toda captura).

## Cuidado conhecido: bug de commit incompleto

Já aconteceu (mesma classe de bug se repetiu depois no
opcoes-sinal-diario): o workflow automático só commitava parte dos
arquivos de saída, deixando outro pra trás silenciosamente. Ao mexer em
`.github/workflows/daily-hilo.yml` ou `hilo_resultados.yml`, conferir que
o `git add` cobre **todos** os arquivos de saída esperados daquela run,
não só o principal.

## Resultados — sem horizonte fixo

Cada linha de `historico_ordens.xlsx` só é gravada quando a posição do
ticker troca (`change==1`) — a ordem "fecha" naturalmente na troca
seguinte do mesmo ticker (holding-period return, sem horizonte fixo,
mesmo padrão do api_OMQS). `resultados.py` roda sob demanda e separa
`fechados`/`abertas_mtm`/`combinado` — "fechados" sozinho é enviesado pra
baixo (só fecha quem perdeu o bastante), ver aviso no `README.md`.

Histórico começou em 2026-07-30 — amostra ainda pequena, tratar como
acompanhamento de tendência, não conclusão fechada.

## Automação

- `.github/workflows/daily-hilo.yml` — seg-sex, ~18:30 BRT via cron da
  VPS (ver seção "Roda em runner próprio" abaixo — não tem mais
  `on:schedule` nativo do GitHub).
- `.github/workflows/hilo_resultados.yml` — só disparo manual.

Secrets necessários: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. (Até 01/09
também precisava de `TV_USERNAME`/`TV_PASSWORD` — não mais, ver seção
"OHLC de hoje" abaixo.)

## OHLC de hoje: TradingView trocado por estimativa via yfinance 1h (01/09)

Pedido do usuário: parar de depender do TradingView pro dia corrente e
usar só yfinance como fonte, mesmo rodando durante o pregão. Antes,
`importar_tradingview()` pegava o candle diário "ao vivo" do TradingView
(via `tvDatafeed`, precisa de `TV_USERNAME`/`TV_PASSWORD`) pra completar
o "hoje" que o `yf.download(..., end=hoje)` não traz (yfinance só publica
o candle diário depois que a B3 fecha e o Yahoo processa). Agora
`estimar_ohlc_intraday()` baixa candles de **1h** do yfinance
(`period="5d", interval="1h"`) e agrega manualmente: Open = abertura do
1º candle de 1h do dia, High/Low = máx/mín entre os candles já fechados,
Close = fechamento do candle de 1h mais recente disponível. Roda perto do
fechamento (18:30 BRT, inalterado) pra minimizar a diferença entre essa
estimativa e o fechamento oficial.

Achado durante o teste (validado com dado real antes de publicar): o
próprio candle diário "oficial" do yfinance pro dia mais recente às vezes
vem com Open/High/Low/Volume zerados (só Close preenchido) — a agregação
por 1h contorna isso de graça, além de resolver a dependência do
TradingView. `tradingview-datafeed` removido de `requirements.txt`.

## Chrome/ChromeDriver do workflow era peso morto (removido 01/09)

O workflow instalava Chrome + ChromeDriver (`browser-actions/setup-chrome`)
mas **nada no código usa Selenium** — nem `projeto_hilo.py`, nem
`resultados.py`, nem `requirements.txt` (só tinha `tradingview-datafeed`,
que é a lib `tvDatafeed`, baseada em WebSocket, não em browser). Esse
passo nunca teve função real — era o motivo citado (errado) pra manter
este repo fora da migração pro runner próprio dos outros 6 (ver seção
abaixo). Removido do workflow.

## Painel de Sinais (artefato compartilhado)

Os números de `resultados.py` (aba `resumo`: fechados/abertas_mtm/
combinado, com ganho/perda médio, extremos, duração) alimentam à mão o
card "Hilo" do artefato **Painel de Sinais**
(`https://claude.ai/code/artifact/ac976eca-35a4-4ff2-ba69-67b1863c29c9`),
que também agrega mia_telegram, api_OMQS (diário + 4h),
opcoes-sinal-diario e api_OMQS_futuros. É HTML estático — os números são
colados à mão a cada atualização, seguindo o comentário HTML antes do
card.

## Incidente 26/08: cron do GitHub Actions sumiu (não é bug daqui)

`daily-hilo.yml` (21:30 UTC / 18:30 BRT) não disparou em 26/08 — não
atrasou, não falhou, sumiu da fila do `on: schedule` inteiro (`gh run
list` sem run pro dia). Backfillado via `workflow_dispatch` manual no
mesmo dia. **Mesmo incidente em pelo menos +4 workflows de outros repos
do usuário na mesma janela ~21:30-22:11 UTC** (mia_telegram, api_OMQS,
api_OMQS_futuros, acoes_fundamentalista) — forte indício de falha da fila
do GitHub Actions, não bug de código. Se os números do card "Hilo"
parecerem defasados, checar `gh run list` por um dia útil inteiro ausente
antes de investigar código — a ausência total do cron não dispara e-mail
de alerta (só `conclusion: failure` dispara, e essa run nem chega a
existir).

## Roda em runner próprio (não GitHub-hosted) desde 01/09

Os outros 5 repos de sinal migraram em 28/08 (fila compartilhada do
GitHub Actions atrasando rodadas — ver `omqs_futuros_5tf/CLAUDE.md`).
**Este repo ficou de fora até 01/09** pela suposição (equivocada — ver
seção acima) de que o Chrome/Selenium do workflow pesava demais de RAM
pra dividir a VPS de 1GB com os outros runners. Com o Chrome removido
(nunca foi usado de verdade) e o TradingView saindo de cena no mesmo
dia (OHLC de hoje agora vem só do yfinance), não sobrou motivo real pra
manter fora — `daily-hilo.yml` passou a usar
`runs-on: [self-hosted, self-hosted-hilo]` e `on:schedule` foi removido
(mesmo padrão dos outros 6, ver `omqs_futuros_5tf/CLAUDE.md` sobre por
que o schedule nativo do GitHub não é mais confiável). Gatilho real
agora é o cron da VPS (`/etc/cron.d/gh-triggers`, ~18:30 BRT,
inalterado). Setup do runner: mesmo procedimento dos outros 6 (registrar
via `POST repos/{repo}/actions/runners/registration-token`, systemd,
label `self-hosted-hilo`, override `Restart=on-failure`) — ver
`omqs_futuros_5tf/CLAUDE.md` pro passo a passo completo.

Migração concluída e testada em 01/09: runner `hilo-runner` registrado
(label `self-hosted-hilo`), serviço systemd com override
`Restart=on-failure`, teste via `workflow_dispatch` passou 100%
(2 trocas de sinal do dia — BBAS3 Compra, PRIO3 Venda — Telegram enviado,
`historico_diario.xlsx`/`historico_ordens.xlsx` commitados, tudo em
~15s). Cron da VPS atualizado com a linha do hilo (18:30 BRT, mesmo
horário de sempre). Secrets `TV_USERNAME`/`TV_PASSWORD` removidos do
repo (sem uso nenhum mais).

Se a VPS mostrar algum problema de RAM agora com 7 runners em vez de 6,
essa é a hipótese a revisitar primeiro (ver
`omqs_futuros_5tf/CLAUDE.md`, recomendação em aberto de subir pra 2GB).

## Estrutura

Ver `README.md`, seção "Arquivos", pra lista completa.
