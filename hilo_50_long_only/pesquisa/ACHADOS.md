# Achados — HiLo long-only

Consolidado do estudo. Seções 1–7 são o estado estabelecido antes de
2026-09-09; seção 8 em diante é o que saiu da revisão de código dessa data.

---

## 1. Amostra

| | Diária | 4h |
|---|---|---|
| Tickers na lista | 100 | 100 |
| Processados | 98 (falham AUAU3, IBOV11) | 98 |
| Marcados suspeitos | 17 | 3 |
| Usados nos agregados | **81** | **95** |
| Período | 2000-01 a 2026-09 (26,2 anos) | 2009-03 a 2026-09 (10,5 anos) |

Suspeitos da diária: AMBP3, B3SA3, BRKM5, CMIG4, CPFE3, CYRE3, GGBR4,
GOAU4, ISAE4, LREN3, NATU3, PCAR3, POSI3, PRIO3, RADL3, UGPA3, UNIP6.

## 2. Cortar o lado vendido — a conclusão mais sólida

- Long-only supera long+short em **99/99 hilos diários** e **197/197 de 4h**,
  bruto e líquido de custo.
- Pareado diário, LongOnly+CDI − LongShort: **p = 0,004 a 0,024**, +8,9 a
  +11,2 p.p. a.a.
- `Expec_Mat_Short` negativo na mediana em toda a faixa de hilo.
- **71% da vantagem existe a custo zero** na diária, 53% no 4h.
- Short só "funciona" em ativos que não subiram — selecioná-los exige
  saber o retorno de 25 anos (look-ahead).

## 3. Remunerar o caixa ocioso é obrigatório

Long-only fica ~45% do tempo fora do mercado. Sem CDI, `LongOnly −
LongShort` dá p = 0,09 a 0,27; com CDI, p = 0,004 a 0,024. É receita
real do desenho, não maquiagem.

## 4. A tese é risco, não alfa

**O alfa não passa em teste em nenhuma configuração** (p = 0,65 a 0,92).
A redução de risco é grande e consistente. "Supera o índice" não se
sustenta: contra o IBOV parece sim (p = 0,036), mas ~10 dos 13 pontos
vêm de equal-weight vs cap-weight e de viés de sobrevivência. Contra o
IDIV, p = 0,45.

## 5. Assimetria de duração — a estatística mais estável

| | Ganho | Perda | Razão |
|---|---|---|---|
| Diária hilo 50, long | 62,0 pregões | 13,7 | **4,54×** |
| 4h hilo 100, long | 53 pregões | 9 | **5,94×** |

Razão > 1 em 81/81 ativos (diária) e 95/95 (4h). Acerta 37,4% mas passa
73,0% do tempo dentro de operações vencedoras. Parte da razão mede o
tamanho da janela, não qualidade de sinal.

## 6. O timeframe não faz diferença

Diferença-em-diferenças com o buy-and-hold de cada timeframe como
controle: efeito bruto −4,81 p.p. a.a. (p = 0,0006), dos quais −4,01
p.p. eram composição de universo. **Efeito líquido: −0,80 p.p., p = 0,58.**

Preferir a diária pelos motivos certos: resistência a custo quase 2×
maior (break-even 348 bps/op contra 181), 2,5× mais histórico, operação
mais simples. **Não** por retorno.

## 7. Hipóteses rejeitadas — não repetir

| Hipótese | Resultado |
|---|---|
| Seleção de hilo em walk-forward (5 critérios) | nenhuma bate hilo fixo |
| Seleção de ativos por esperança acumulada | pior que não selecionar (4,69% vs 6,19% a.a.) |
| Efeito setorial | ranking não persiste (Spearman 0,17, p = 0,53) |
| Payoff como critério | `Spearman(comprimento, payoff) = +0,84` — mede a janela |
| Vol do ativo explica desempenho | Spearman 0,18, p = 0,16 |

**O agregado é plano de ~36 a 95 pregões.** Nenhum critério de seleção
adiciona retorno escolhendo dentro de região plana — é a explicação
unificadora de por que todas as camadas de seleção falharam.

---

## 8. Bug: retorno de notional fixo composto contra buy-and-hold real

**Onde:** `hilo_walkforward_payoff_v8.py`, construção de
`series_longonly` (~linha 2084) e `montar_longonly_vs_bh`.

A série da estratégia é `pnl / montante_inicial`, onde
`pnl = qtd × ΔP` e `qtd = montante_inicial / P_entrada` — ou seja
`r_t = (P_t − P_{t−1}) / P_entrada`. O buy-and-hold usa
`holding.pct_change()`, isto é `(P_t − P_{t−1}) / P_{t−1}`.

Denominadores diferentes: dentro de uma operação vencedora a exposição
efetiva da estratégia cresce (a posição vale mais que o notional) mas o
retorno continua dividido pelo capital inicial. Aí `np.cumprod(1+r)`
compõe essa série como se fosse taxa sobre patrimônio corrente. O
comentário do topo do arquivo descreve `"composto"` como "posição
redimensionada ao patrimônio corrente" — a conta não implementa isso.

**Efeito medido** (carteira equal-weight, 81 ativos limpos, hilo 50,
custo 30 bps, 2000–2026). Coluna A = como o código faz; B = com
`pct_change` verdadeiro:

| | Rent a.a. | Vol | Sharpe | DD | Vol/B&H | DD/B&H | Alfa |
|---|---|---|---|---|---|---|---|
| LongOnly+CDI **A** | 22,32 | 14,44 | 1,468 | −22,69 | 0,629 | 0,389 | **+3,03** |
| LongOnly+CDI **B** | 18,54 | 11,89 | 1,490 | −16,43 | **0,518** | **0,282** | **−0,75** |
| BuyAndHold | 19,29 | 22,97 | 0,884 | −58,26 | 1,000 | 1,000 | 0,00 |

A versão A foi reproduzida exatamente contra a planilha (Vol/BH 0,629,
DD/BH 0,389), o que valida a replicação.

**Consequência — a correção melhora a tese, não piora:**
- o alfa residual de +3,03 p.p. era artefato; corrigido dá **−0,75 p.p.**
  Reforça a seção 4: não há alfa, e agora sem número teimoso no caminho.
- a redução de risco é **maior** que a reportada: vol 0,518 do B&H (não
  0,629) e drawdown **0,282** (não 0,389).
- Sharpe praticamente não muda (1,49 vs 1,47) — é o que se espera, já
  que o viés infla numerador e denominador juntos.
- long-only vs long+short fica **mais** forte (gap +11,2 → +12,8 p.p.).

Frase corrigida da tese: *retorno equivalente ao buy-and-hold (−0,8 p.p.)
com 28% do drawdown e 52% da volatilidade.*

## 9. Bug: CDI creditado antes do IPO nas linhas por ativo

**Onde:** `montar_longonly_vs_bh`, laço por ativo (`iv = inv[a].fillna(0.0)`).

`rl/ro/rb/inv` são reindexados pela **união** das datas de todos os
ativos. Para um ativo que estreou depois, o período anterior vira NaN →
`fillna(0)` → `investido = 0` → a variante LongOnly+CDI ganha CDI todo
dia em que **o ativo ainda não existia**, enquanto o buy-and-hold ganha 0.

Visível na planilha: todo ativo aparece com `N_Barras = 6599` e
`Anos = 26,19`, inclusive XPBR31 (IPO em 2021, 1.227 barras reais) e
ROXO34 (2021, 1.183):

| Ativo | LongOnly+CDI | BuyAndHold |
|---|---|---|
| XPBR31 | **+693,9%** (8,23% a.a.) | −48,1% |
| ROXO34 | **+814,9%** (8,82% a.a.) | +31,7% |

São ~20 anos de CDI sobre ação inexistente.

**Alcance:** confinado às linhas **por ativo** de `LongOnly_vs_BH`. A
linha `CARTEIRA_EQUAL_WEIGHT`, `LongOnly_Subamostras`, `LongOnly_Testes`
e os agregados normalizam por `vivos`/máscara `vivo` e estão corretos —
as conclusões das seções 2 a 7 não dependem das linhas por ativo.

**Correção:** recortar cada ativo à sua própria janela viva antes de
`_emitir` (ex.: `serie.first_valid_index()` / `last_valid_index()`).

## 10. Pendência #3 respondida: a vantagem não depende de 2008

Rodando a carteira só a partir de 2009-01-01 (versão B, corrigida):

| | 2000–2026 | 2009–2026 |
|---|---|---|
| LongOnly+CDI rent a.a. | 18,54 | 16,74 |
| LongOnly+CDI **drawdown** | **−16,43** | **−16,43** |
| B&H drawdown | −58,26 | −47,95 |
| DD / B&H | 0,282 | 0,343 |
| Sharpe | 1,490 | 1,429 |
| Alfa | −0,75 | −0,88 |

**O drawdown da estratégia é idêntico com e sem 2008 (−16,43%)** — o
pior momento dela não foi 2008. A razão DD/B&H piora só porque o
denominador encolhe. A vantagem de risco não vem de um evento único.

## 11. Convenção de sinal: produção ≈ pesquisa

A pesquisa usa `rolling(n).mean().shift(2)` comparado a `Close.shift(1)`;
o `projeto_hilo.py` usa `shift(1)` comparado ao `Close` do dia — 1 barra
mais rápido. Testado na carteira de 81 ativos:

| Convenção | HiLo | Rent a.a. | Vol | Sharpe | DD |
|---|---|---|---|---|---|
| pesquisa | 50 | 18,54 | 11,89 | 1,49 | −16,43 |
| produção | 50 | 18,37 | 11,92 | 1,48 | −17,59 |
| pesquisa | 70 | 18,08 | 11,96 | 1,45 | −19,17 |
| produção | 70 | 17,83 | 11,93 | 1,43 | −16,72 |

Indistinguível. `hilo_long_only.py` usa a convenção de produção, por
coerência com o `projeto_hilo.py` da raiz.

---

## 12. Call ATM rolada no lugar da ação

**Pergunta:** no sinal HiLo 50 long-only, comprar a call ATM do próximo
vencimento com mais de 20 dias corridos, rolar quando faltar menos de
10, sempre ATM, até o HiLo zerar — bate comprar a ação?

**Código:** `pesquisa/calls/`. **Fonte:** `/app/volatilidade_implicita/
vol_implicita.db` (COTAHIST 2000–2026, 4,6 M cotações de opção com
strike/vencimento/bid/ask). O repo `opcoes-sinal-diario` **não** serve:
`data/raw` está vazio, o `.db` não é versionado e ele só cobre PUT de
7 ativos em shadow mode desde 08/2026.

### 12.1 Só 6 ativos são operáveis

O COTAHIST só grava opção que **negociou**. Cobertura dos episódios
long do HiLo 50:

| Ativo | Episódios cobertos | Marcação por modelo |
|---|---|---|
| PETR4 | 76/78 (97%) | 13,9% |
| BBAS3 | 76/87 (87%) | 29,2% |
| ITUB4 | 70/81 (86%) | 19,8% |
| BBDC4 | 67/79 (85%) | 25,9% |
| BOVA11 | 45/72 (63%) | 19,6% |
| VALE3 | 45/88 (51%) | 5,0% |
| PETR3 | 33/70 (47%) | 38,6% |
| SMAL11 | 16/65 (25%) | 22,9% |

**6 de 81 ativos** têm call ATM negociável com regularidade. A ideia não
é aplicável à carteira — só a um punhado de nomes.

### 12.2 Desenho do teste

- Sinal HiLo 50 long-only em preço **ajustado**; perna de opção em preço
  **bruto** do COTAHIST (é o que casa com o strike).
- ATM = contrato de **delta mais próximo de 0,5**, tolerância 0,20. Usar
  "strike mais próximo do forward" produz erro grosseiro em dia ralo
  (visto: 2010-12-27, PETRA4, delta 0,009 escolhido como ATM).
- Só vencimentos **mensais** (`semanal=0`).
- Teste final usa **563 pernas / 314 episódios com as duas pontas em
  preço de mercado** — nenhuma marcação por modelo entra no resultado.
- `preco` é mid ou último do dia, ambos de fechamento — **sem
  look-ahead** contra um sinal apurado no fechamento.
- Dimensionamento **delta-equivalente**: `w = prêmio / (delta × strike)`
  do capital vai pro prêmio, o resto rende CDI. Mediana **w = 6,6%**.
- Ação paga 30 bps por **episódio** (não por perna — ela atravessa as
  rolagens); CDI no tempo ocioso dos dois lados.

### 12.3 Resultado: a convexidade paga, o spread come

Taxa de composição a.a. do sleeve, por nível de spread (% do mid por lado):

| Spread | Mediana call − ação | Ativos em que a call ganha |
|---|---|---|
| 0% (mid-a-mid) | **+3,34 p.p.** | 6/6 |
| 2% | +1,94 p.p. | 6/6 |
| 5% | −0,38 p.p. | 2/6 |
| 10% | −3,37 p.p. | 0/6 |

**Ponto de equilíbrio ≈ 4–5% por lado.** A vantagem a mid é real e
consistente — e faz sentido mecanicamente: o HiLo segura vencedor 4,5×
mais tempo que perdedor (seção 5), então o gama trabalha a favor.

### 12.4 Mas o spread medido está acima do equilíbrio

Meio spread bid-ask em % do mid (calls ATM, delta 0,35–0,65, mensais,
10–60 dias) — **medido na base, não assumido**:

| Ativo | p25 | Mediana | Call − ação no p25 | Call − ação na mediana |
|---|---|---|---|---|
| PETR4 | 2,83% | 6,65% | **+2,53** | −2,09 |
| VALE3 | 3,79% | 8,28% | +0,15 | −2,57 |
| BOVA11 | 3,53% | 8,11% | −0,45 | −2,49 |
| BBDC4 | 7,87% | 15,04% | −2,40 | −5,82 |
| BBAS3 | 9,32% | 17,75% | −2,74 | −8,09 |
| ITUB4 | 12,00% | 22,78% | −3,70 | −9,12 |
| **Mediana** | | | **−1,43** | **−4,19** |

Ganha em 2/6 no p25 e **0/6** no spread mediano.

### 12.5 Conclusão

**Não substituir a ação pela call como regra.** A vantagem existe antes
de custo (+3,3 p.p. a.a., 6/6 ativos) mas o spread medido supera o ponto
de equilíbrio em todos os 6. Só **PETR4** sobrevive com folga, e só
executando no quartil bom do spread (≤2,8% por lado).

Ressalvas que empurram nos dois sentidos:
- bid/ask do COTAHIST é fechamento e só ~50% preenchido — spread
  intradiário real provavelmente **menor**, então o p25 é a estimativa
  mais justa. É por isso que a coluna p25 está na tabela.
- w mediano de 6,6% significa que **93% do capital fica em CDI**; o
  resultado é sensível à taxa assumida (10% a.a.).
- 563 pernas em 6 ativos correlacionados — não são 563 observações
  independentes.

**Variante literal rejeitada:** colocar 100% do capital em prêmio (em vez
do delta-equivalente) dá −97% a.a. e vol de 392%. Com w mediano de 6,6%,
isso é ~15× de alavancagem sobre o ativo; a ruína é aritmética, não azar.

## 13. Pendências

**Alta**
1. Recoletar a base diária via tvDatafeed para eliminar os 17 suspeitos.
2. Medir o custo de transação real da **ação** (os 30 bps são chute).
3. Corrigir os bugs 8 e 9 no `hilo_walkforward_payoff_v8.py` e regerar.

**Média**
4. Rótulo das colunas de janela no `hilo_4h.py` (nomear em pregões).
5. Rodar a diária nos mesmos 95 ativos e período do 4h.
6. Validar fora da B3 — falta de janelas independentes é o limite de tudo.

**Baixa**
7. Unificar o cálculo de esperança (`Expec_Mat_WF` usa fórmula
   reconstruída; o seletor usa média direta).
