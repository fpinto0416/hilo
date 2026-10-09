# hilo_50_long_only

Subprojeto do [hilo](https://github.com/fpinto0416/hilo). Duas partes:

| | O quê |
|---|---|
| `hilo_long_only.py` | **Executável diário.** HiLo 50 fixo, long-only, 81 ativos. Roda junto com o `projeto_hilo.py` da raiz e manda no mesmo Telegram. |
| `pesquisa/` | **P&D.** Os scripts que produziram as conclusões. Não roda no dia a dia. |

A tese, em uma linha: **retorno equivalente ao buy-and-hold com ~1/3 do
drawdown e ~metade da volatilidade, usando ~55% do capital exposto.**
Não é "supera o índice" — o alfa não passa em teste. Ver
[`pesquisa/ACHADOS.md`](pesquisa/ACHADOS.md).

## Por que este subprojeto existe

O `projeto_hilo.py` da raiz opera long **e** short, com janela de HiLo
calibrada por ativo. A pesquisa mostrou que as duas escolhas custam caro:

1. **A perna vendida destrói valor.** Long-only supera long+short em
   99/99 hilos diários e 197/197 de 4h, bruto e líquido de custo
   (p = 0,004 a 0,024). 71% da vantagem existe a custo zero — o custo
   amplifica, não cria.
2. **A janela por ativo não ajuda.** Nenhum critério de seleção bateu
   hilo fixo, e o agregado é plano de ~36 a 95 pregões. Das 29 janelas
   do `projeto_hilo.py`, **24 estão abaixo de 36** — fora do platô.

## Rodar

```bash
# diário (produção)
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python hilo_long_only.py

# P&D
HILO_DADOS_BASE=/app/projeto_MIA26/database \
HILO_FIXOS_JANELAS="20,50,70,90" HILO_CUSTO_JANELAS=30 \
python pesquisa/hilo_walkforward_payoff_v8.py
```

`saidas_wf_hilo.xlsx` (31 MB, 20 abas) **não é versionado** — é
regenerável e infla o repo permanentemente. Ver `.gitignore`.

## Saídas do diário

| Arquivo | Conteúdo |
|---|---|
| `historico_diario_long_only.xlsx` | 1 linha por ativo/dia: preço, hi, lo, Comprado/Caixa |
| `historico_ordens_long_only.xlsx` | 1 linha por troca: Compra ou Zera |

Ambos idempotentes por dia — um rerun substitui as linhas do dia em vez
de duplicar (bug real já visto na raiz em 27/08).
