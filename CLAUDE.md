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

- `.github/workflows/daily-hilo.yml` — seg-sex, 21:30 UTC (~18:30 BRT).
- `.github/workflows/hilo_resultados.yml` — só disparo manual.

Secrets necessários: `TV_USERNAME`/`TV_PASSWORD` (TradingView, fallback de
preço), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

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

## Continua no GitHub-hosted (não migrou pro runner próprio, 28/08)

Os outros 5 repos de sinal (mia_telegram, api_OMQS, api_OMQS_futuros,
acoes_fundamentalista, opcoes-sinal-diario) migraram pra um runner
próprio numa VPS dedicada depois de dias seguidos de atraso grave na
fila compartilhada do GitHub Actions — ver `omqs_futuros_5tf/CLAUDE.md`
pro relato completo. **Este repo ficou de fora de propósito**: usa
Chrome/Selenium (`browser-actions/setup-chrome`) pra raspar o
TradingView, bem mais pesado de RAM que os outros (que são só
pandas/requests) — a VPS é de 1GB e rodar Chrome ao lado de outros
runners tinha risco real de falta de memória. Decisão: manter aqui, já
que é job 1x/dia EOD — um atraso de horas na fila do GitHub não perde
dado de verdade (diferente da captura intradiária do omqs_futuros_5tf,
que é o que motivou a migração dos outros). Se esse repo também começar
a ficar 1 dia inteiro sem rodar (não só atrasado), vale reconsiderar —
nesse caso, aumentar a VPS pra 2GB antes de migrar o Chrome pra lá
também.

## Estrutura

Ver `README.md`, seção "Arquivos", pra lista completa.
