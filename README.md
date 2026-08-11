# hilo

Sinal diário de tendência (HiLo Activator — média móvel do high/low, janela
por ativo) para ~30 tickers B3. Roda sozinho via GitHub Actions, envia
Compra/Venda no Telegram e acumula `historico_ordens.xlsx`.

## Arquivos

| Arquivo | Papel |
|---|---|
| `projeto_hilo.py` | Calcula o HiLo do dia, detecta troca de posição, envia Telegram, acumula `historico_ordens.xlsx` |
| `resultados.py` | Calcula o payoff realizado de cada troca de posição (sob demanda) |
| `historico_ordens.xlsx` | Uma linha por troca de posição (data, ticker, ordem, price, hilo) — versionado |
| `resultados/*.xlsx` | Saída de `resultados.py` (abas `trades_fechados`, `posicoes_abertas`, `resumo`) — versionado |

## Automação

- `.github/workflows/daily-hilo.yml` — roda `projeto_hilo.py` seg-sex, 21:30 UTC (~18:30 BRT), commita `historico_ordens.xlsx`.
- `.github/workflows/hilo_resultados.yml` — só disparo manual (Actions → Run workflow), roda `resultados.py` e commita `resultados/`.

## Resultados

Cada linha de `historico_ordens.xlsx` é gravada só quando a posição do
ticker troca (`change==1`), então cada ordem "fecha" naturalmente na ordem
seguinte do mesmo ticker — não há horizonte fixo, é holding-period return.

```bash
python resultados.py
```

A aba `resumo` traz, por grupo (`geral`, `ordem_Compra`, `ordem_Venda`):
`acerto`, `retorno_medio`, `retorno_total`, `ganho_medio`, `perda_media`
e `profit_factor` (soma dos ganhos / soma das perdas em módulo — >1
significa que ganhos pesam mais que perdas).

Ressalva: histórico começou em 2026-07-30 — amostra ainda pequena, tratar
como acompanhamento de tendência, não conclusão.

## Setup

Cadastrar em Settings → Secrets and variables → Actions:

- `TV_USERNAME` / `TV_PASSWORD` (TradingView, usado como fallback de preço)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
