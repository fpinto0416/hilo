# CLAUDE.md — hilo_50_long_only

Subprojeto do repo `hilo`. Leia `README.md` e `pesquisa/ACHADOS.md`
antes de qualquer mudança maior.

## Divisão

- `hilo_long_only.py` — **produção**, roda todo dia junto com o
  `projeto_hilo.py` da raiz. HiLo 50 fixo, long-only, 81 ativos.
- `pesquisa/` — **P&D**, roda sob demanda. Não mexer nele achando que
  afeta o sinal diário; não afeta.

## O que já foi testado e falhou — não repetir

Ver `pesquisa/ACHADOS.md` §7. Resumo: **nenhum critério de seleção
(de hilo ou de ativo) bate hilo fixo**, porque o agregado é plano de ~36
a 95 pregões. Antes de propor mais uma camada de seleção, releia isso.

## Regras metodológicas que já custaram caro

- **Janela móvel sobreposta não é tamanho amostral.** 6.500 janelas de
  250 dias vêm de ~26 independentes. Reportar `Janelas_Independentes` e
  testar com esse n. Resultados que pareciam fortes (87,9% vs 77,9%) se
  resolveram em 4 pares discordantes, p = 0,125.
- **Usar o buy-and-hold como controle** quando universos ou períodos
  diferirem. Se o B&H também diferir, a diferença não é da estratégia.
  Foi assim que o "4h é pior" (−4,81 p.p., p = 0,0006) virou −0,80 p.p.,
  p = 0,58.
- **Filtrar por métrica de período completo é look-ahead.** O filtro
  `Esperanca_WF > 0,10` rendia 13,25% a.a. no papel e 4,69% implementável.
- **Escolher a região do platô, não o argmax.** O pico se move a cada
  sorteio de carteira (P10=29, P90=95).
- **Comparar duas séries exige o mesmo denominador.** Foi exatamente
  isso que gerou o bug do §8 (notional fixo vs `pct_change`).

## Bugs já corrigidos — não reintroduzir

1. `pct_change` de curva aditiva encadeada entre hilos — encadear o
   **pnl em R$**, nunca a curva.
2. `np.column_stack` com históricos heterogêneos — usar
   `pd.DataFrame({...}).reindex()`.
3. Atribuição encadeada sob Copy-on-Write (`df.iloc[a:b][cols] = x`) —
   falha em silêncio no pandas ≥ 3.0. Usar `.loc[idx, cols]`.
4. Multiplicador de Benjamini-Hochberg invertido (`m/(m−i)` vs `m/i`).
5. DSR com `n_trials` = nº de hilos; o correto é o **nº de ativos**.
6. Aquecimento do indicador contado como lacuna.
7. RNG avançando entre hilos, quebrando o pareamento das simulações.
8. `252` hardcoded na versão 4h (com 2 barras/pregão o ano tem 504).

## Bugs ABERTOS no P&D (achados em 09/09/2026)

Ver `pesquisa/ACHADOS.md` §8 e §9. Nenhum dos dois derruba as conclusões
principais — o §8 na verdade **melhora** a tese e o §9 está confinado às
linhas por ativo — mas a planilha atual carrega os dois:

- **§8**: série da estratégia é notional fixo (`ΔP/P_entrada`) composta
  contra buy-and-hold real (`ΔP/P_{t−1}`). Infla retorno e vol.
- **§9**: CDI creditado no período **anterior ao IPO** do ativo nas
  linhas por ativo de `LongOnly_vs_BH` (XPBR31 aparece com +694%).

## Saída de 31 MB não é versionada

`saidas_wf_hilo.xlsx` está no `.gitignore` — é regenerável e infla o
repo permanentemente (o repo inteiro tem <1 MB de histórico). Se precisar
compartilhar número, extraia a aba em CSV.

## Análise de opções

`pesquisa/calls/` — call ATM rolada no lugar da ação. Fonte é
`/app/volatilidade_implicita/vol_implicita.db` (COTAHIST), **não** o
`opcoes-sinal-diario` (que só tem PUT de 7 ativos, shadow mode, e não
versiona o `.db`). Conclusão em `ACHADOS.md` §12: vantagem real a
mid-a-mid, mas o spread medido come tudo em 6/6 ativos. Não virar regra.
