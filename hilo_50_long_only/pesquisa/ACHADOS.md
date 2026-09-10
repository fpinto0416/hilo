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

### 12.1 Só 6 ativos foram TESTÁVEIS — e isso era limitação da base

**CORREÇÃO (10/09/2026).** A versão anterior desta seção dizia "só 6 de
81 ativos têm call ATM negociável". **Está errado.** O `vol_implicita.db`
tem 12 ativos porque o ETL dele foi configurado para 12 — não porque a B3
só tenha opção neles. Varrendo o COTAHIST de 2025 direto: **155 raízes**
com call negociada em 100+ pregões, e **~74 dos 81 ativos** da carteira
long-only estão entre elas.

O que segue vale para os 6 ativos que a base cobria, e a cobertura de
episódios abaixo é a cobertura **na base consultada**, não no mercado:

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

Ou seja: o teste rodou em 6 ativos porque a base tinha 6, não porque o
mercado tenha 6. O acervo Parquet criado em `opcoes-sinal-diario`
(`data/opcoes/`) existe para remover essa limitação — ver §12.6.

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

### 12.5 Conclusão (dentro dos 6 ativos testados)

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

### 12.6 O que muda com o acervo Parquet — e o que não muda

Com ~74 ativos em vez de 6, a **penalidade de cobertura** (§12.7 abaixo,
−6,2 p.p. a.a.) deve encolher muito: ela vinha de o sinal disparar em dia
sem call negociável na base. O **spread**, não. Os nomes que entram são
mais finos que os 6 testados, e spread de opção piora com liquidez — a
expectativa honesta é que a cobertura melhore e o pedágio piore.

**Primeira medição sobre o acervo (10/09/2026).** As duas metades da
previsão acima se confirmaram, e o saldo é negativo.

*Cobertura:* virou ~100%. WEGE3, MGLU3 e SUZB3 — nenhum deles na base
antiga — têm call ATM mensal com >20 dias corridos em **501 de ~500
pregões** de 2024–2025, contra os 51–97% da base de 6. A penalidade de
−6,2 p.p. do §12.7 praticamente desaparece.

*Spread:* piorou muito. Meio spread bid-ask (% do mid, um lado), calls
mensais de 10–60 dias com |ln(K/S)|<0,05, em 2024–2025:

| Ativo | p25 | Mediana |
|---|---|---|
| BOVA11 | 2,9% | 5,8% |
| PETR4 | 2,8% | 5,9% |
| VALE3 | 3,3% | 7,1% |
| BBDC4 | 5,7% | 10,4% |
| BBAS3 | 6,7% | 12,8% |
| MGLU3 | 7,7% | 16,3% |
| B3SA3 | 9,8% | 19,3% |
| ABEV3 | 11,5% | 20,7% |
| ITUB4 | 10,8% | 22,0% |
| WEGE3 | 15,5% | 31,2% |
| SUZB3 | 14,8% | 32,1% |
| EQTL3 | 33,3% | 58,1% |

(PETR4 deu 5,9% aqui contra 6,65% medido na base antiga, e o ranking é
idêntico — a medição está calibrada.)

**O ponto de equilíbrio é ~4–5% por lado.** Só BOVA11, PETR4 e VALE3
chegam perto, e apenas no quartil bom de execução. Todo ativo que o
acervo acrescentou está de 3× a 12× acima do equilíbrio.

**Conclusão revista:** ampliar o universo não salva a estratégia de call —
troca uma restrição de cobertura por um pedágio maior. Ela continua
defensável só nos 3 nomes mais líquidos, e só executando perto do mid.
Os números de §12.3 a §12.5 seguem valendo para os 6 ativos testados;
o que mudou é que agora sabemos que ampliar não ajuda.

### 12.8 RESULTADO DEFINITIVO — 50 ativos sobre o acervo (10/09/2026)

Refeito por inteiro sobre `acervo-opcoes-b3`: **50 ativos, 2015–2026,
2.396 pernas em 1.398 episódios** — 4× a amostra da versão de 6 ativos.
Substitui §12.3 a §12.7 como número de referência.

Método: sinal HiLo 50 long-only em preço ajustado; call ATM (delta
mediano **0,560**, |ln(K/S)| mediano 0,004) do 1º vencimento mensal com
>20 dias corridos, rolada a <10; **preço de mercado (`ultimo`) nas duas
pontas**; delta por Black-Scholes com IV extraída do próprio preço;
dimensionamento delta-equivalente (**w mediano 7,8%** do capital em
prêmio, resto em CDI); ação paga 30 bps por episódio.

**Carteira equal-weight, nos episódios cobertos:**

| Execução | Call a.a. | Ação a.a. | Dif | Ativos em que a call ganha |
|---|---|---|---|---|
| mid-a-mid | **11,43%** | 6,61% | **+4,81 pp** | 45/50 |
| p25 medido | 2,91% | 6,61% | −3,71 pp | 8/50 |
| mediana medida | −2,66% | 6,61% | −9,28 pp | 3/50 |

**Mas a comparação que decide é contra a estratégia COMPLETA em ação**
(mesmos 50 ativos, mesmo período, sem exigir call negociável):

| | Rent a.a. | Vol | Sharpe | Drawdown |
|---|---|---|---|---|
| **Ação long-only + CDI (completa)** | **14,39%** | 12,21 | 1,16 | −15,87% |
| Call ATM rolada, a mid-a-mid | 11,43% | — | — | — |
| Buy & hold | 15,17% | 24,21 | 0,71 | −48,52% |

**Mesmo a custo zero a call perde da ação (11,43% contra 14,39%)**,
porque só **58% dos episódios** (1.397 de 2.390) têm call ATM negociável
com o vencimento certo — nos outros 42% a versão em call fica em CDI
enquanto a ação está comprada. É o mesmo mecanismo do §12.7, atenuado
mas não eliminado pelo universo maior.

**Única exceção — os 3 nomes líquidos** (PETR4, VALE3, BOVA11, 261
pernas), onde a call ganha de forma estatisticamente firme:

| Execução | Dif por perna | p | Call ganha |
|---|---|---|---|
| mid | +1,383 pp | <0,0001 | 62,5% |
| p25 medido | +0,831 pp | 0,0008 | 57,1% |
| mediana medida | +0,175 pp | 0,43 | 49,8% |

**Veredito:** comprar a ação vence comprar a call, no agregado e em
qualquer nível de custo realista. A convexidade é real (+4,81 pp a mid,
45/50 ativos) mas não cobre nem o pedágio nem o custo de ficar de fora
de 42% dos sinais. Só faz sentido em PETR4/VALE3/BOVA11 e com execução
no quartil bom.

**Correção de método achada aqui:** a primeira passada usou `medio` (VWAP
do dia) como preço de entrada da opção. O sinal do HiLo só é conhecido no
**fechamento**, então comprar pelo VWAP é look-ahead — em dia de alta o
VWAP fica abaixo do fechamento e barateia a call de graça. Trocado por
`ultimo`. Valia **2,7 p.p. a.a.** de vantagem falsa (mid-a-mid caiu de
+7,47 para +4,81 pp). Um segundo look-ahead, no baseline em ação, dava
54% a.a. com Sharpe 3,66 — sinal do dia aplicado ao retorno do próprio
dia, sem defasar.

**Não reportável:** vol e drawdown da versão em call. Exigem marcar a
opção todo dia, e toda tentativa de marcar por modelo produziu artefato
(vol anualizada de 82% a.a.).

### 12.7 A restrição de cobertura custa mais que a convexidade paga

Nos 6 ativos, 2009–2026, mesma construção de carteira:

| Versão | Retorno a.a. | Exposição |
|---|---|---|
| Buy & hold | 14,76% | 100% |
| Ação, sinal long-only completo | **10,57%** | 55% |
| Ação, só nos episódios com call na base | 4,39% | 30% |
| Call ATM rolada, mid-a-mid | ~7,4% | 30% |

Exigir call negociável derruba o retorno em **−6,2 p.p.**; a convexidade
devolve no máximo +3,0 p.p. Mesmo a custo zero, a versão em call perde da
ação. **Mas esse número é da base de 6 ativos** — é exatamente ele que
deve mudar com o acervo.

Vol e drawdown da versão em call não são reportáveis: exigem marcar a
opção todo dia, e as duas tentativas deram vol de 82% a.a. — artefato da
marcação por modelo, não resultado.

**Variante literal rejeitada:** colocar 100% do capital em prêmio (em vez
do delta-equivalente) dá −97% a.a. e vol de 392%. Com w mediano de 6,6%,
isso é ~15× de alavancagem sobre o ativo; a ruína é aritmética, não azar.

## 13. Pendências

**Alta**
0. **Refazer §12 sobre o acervo Parquet de `opcoes-sinal-diario`**
   (`data/opcoes/`), com ~74 ativos em vez de 6. É a pendência que mais
   muda conclusão — ver §12.6.
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


### 12.9 Regras v2 — liquidação no vencimento (10/09/2026)

Regras ajustadas a pedido: (1) ATM = strike negociado mais próximo, **sem
tolerância**; (3) vencimento mensal com **>22 dias**, escolhendo entre os
elegíveis o de **maior liquidez** no strike ATM, não o mais próximo;
(4) rolar quando faltar <10 dias **e houver negócio**; não conseguindo,
**levar à liquidação** — no vencimento o valor é o intrínseco
`max(S−K,0)`, que não depende de existir comprador — e reentrar se o HiLo
seguir comprado. Mesmo tratamento na saída do sinal.

**A regra 4 é a que importa.** Ela ataca a perda que não era do desenho
da estratégia e sim da microestrutura: contrato sem comprador no dia da
saída.

| | v1 | **v2** |
|---|---|---|
| Episódios cobertos | 58% | **83%** |
| Pernas | 2.396 | **3.430** |
| Call a mid-a-mid | 11,43% a.a. | **17,32% a.a.** |
| Call no p25 do spread | 2,91% | 4,08% |
| Call na mediana do spread | −2,66% | −4,06% |
| **Ação long-only completa** | **14,39%** | **14,39%** |

A mid-a-mid a v2 **passa a bater a ação** (17,32% contra 14,39%), o que a
v1 não fazia. Em qualquer custo realista continua perdendo.

**De onde vem o ganho — e por que ele é frágil.** As 343 pernas que vão a
liquidação rendem **+168% em média**, e são justamente as de contratos
**menos líquidos** (mediana de 2 negócios no dia da entrada, contra 8 no
geral). Não é bug: com `w` ≈ 8% e delta 0,56, um movimento de +10,7% na
ação — a mediana dessas pernas — vira ~+130% na call. E 81% delas vencem
dentro do dinheiro, o que é esperado, já que só chegam ao vencimento os
casos em que o HiLo continuou comprado, isto é, a ação subindo.

O ponto é outro: a v1 **descartava** essas pernas, e elas são
desproporcionalmente vencedoras. Ou seja, **a v1 era enviesada para
baixo** — descartava não aleatoriamente, mas exatamente onde o contrato
parava de negociar, que correlaciona com movimento grande.

**Teste de robustez — exigir liquidez mínima no contrato na entrada:**

| Mín. negócios | Cobertura | Call mid | Call p25 | Dif vs ação restrita (p25) |
|---|---|---|---|---|
| 1 (sem exigência) | 82% | **17,32%** | 4,08% | −4,22 |
| 3 | 64% | 14,05% | 4,77% | −3,07 |
| 5 | 54% | 12,96% | 5,28% | −2,76 |
| 10 | 44% | 11,64% | 6,34% | −1,32 |
| 20 | 33% | 11,26% | 7,47% | −0,51 |
| 50 | 20% | 11,39% | 8,94% | +0,61 |

**O ganho a mid some quando se exige liquidez.** Com ≥10 negócios no dia
da entrada a call cai para 11,64%, abaixo dos 14,39% da ação — e a
cobertura cai para 44%. Exigir liquidez melhora o resultado líquido de
spread (p25 sobe de 4,08% para 8,94%) mas destrói a cobertura, e em
nenhum patamar a call bate os 14,39% da ação com custo realista.

**Veredito da v2:** as regras novas são melhores — corrigem um viés real
da v1 e elevam a cobertura de 58% para 83%. Mas a conclusão não muda:
**comprar a ação continua vencendo**, porque o único cenário em que a
call ganha (mid-a-mid, sem exigir liquidez) depende de executar ao preço
de contratos que negociaram 2 vezes no dia.

Filtro de dados aplicado: 25 pernas (0,7%) descartadas por evento
societário — retorno do spot bruto do acervo divergindo >15 p.p. do
ajustado, o que deixa o par strike/spot inconsistente e o intrínseco
errado.


### 12.10 Dimensionamento — o que está sendo comparado

Ponto levantado em 10/09 e que não estava escrito: **a comparação não usa
o mesmo montante financeiro nos dois lados.** Usa a mesma **exposição ao
ativo** (delta-equivalente):

- **Ação:** 100% do capital do sleeve comprado na ação.
- **Opção:** `w = prêmio / (delta × spot)` do capital no prêmio — mediana
  **8,2%** na call seca, **8,9%** na trava — e o restante rendendo CDI.

Os dois lados começam com a mesma sensibilidade ao papel. Igualar o
montante financeiro compararia exposições completamente diferentes.

| Dimensionamento | Prêmio | Resultado |
|---|---|---|
| Mesmo montante financeiro | 100% do capital | **−97% a.a., vol 392%** |
| **Delta-equivalente** (usado) | ~8% do capital, resto em CDI | §12.8/§12.9 |
| Prêmio fixo do capital | a definir | não testado |

Com `w` ≈ 8%, colocar todo o capital em prêmio é ~12× de alavancagem
sobre o ativo — a ruína é aritmética, não azar.

**O delta-equivalente favorece a opção**, e vale ter isso claro ao ler os
resultados: ela começa com a mesma exposição mas perde no máximo o prêmio
(~8% do sleeve), enquanto a ação carrega a queda inteira. A convexidade
entra de graça na comparação — e mesmo assim a ação vence.

### 12.11 Trava de alta (compra delta 50 / vende delta 15)

Mesmas regras v2, trocando a call seca por spread vertical de mesmo
vencimento. Delta de compra mediano 0,498, de venda 0,158, líquido 0,338.

| | Call seca (§12.9) | **Trava** |
|---|---|---|
| Episódios cobertos | 83% | **72%** |
| Pernas | 3.430 | 3.032 |
| Prêmio líquido / spot | ~4,6% | **2,87%** |
| Teto / prêmio | — | 3,6× |
| **Mid-a-mid** | **17,32%** | **11,49%** |
| **p25 do spread** | **4,08%** | **−7,19%** |
| Mediana do spread | −4,06% | −17,69% |
| Maior perna | +3.297% | +1.291% |
| Liquidação (retorno médio) | +168% | +76,5% |

**A trava é pior em tudo**, e perde da ação (14,39%) até a mid-a-mid.

Três mecanismos, todos medidos:

1. **O teto corta a cauda.** As pernas de liquidação eram o motor do
   resultado da §12.9 (+168% em média); com teto de 3,6× caem para
   +76,5%. Num sinal cuja assimetria de duração é 4,54× (§5) — segura
   vencedor muito mais tempo que perdedor — limitar o ganho ataca
   exatamente o que a estratégia faz de melhor.
2. **O custo dobra sobre um prêmio menor.** Cruza-se spread nas duas
   pernas, e o prêmio líquido é 2,87% do spot contra 4,6% da call seca.
   O pedágio relativo explode: no p25 a trava vai a −7,19% contra +4,08%
   da call seca.
3. **A cobertura cai** de 83% para 72%, porque agora as **duas** pernas
   precisam ter negociado. E `liquidacao_saida` — perna que morre sem
   valor — dobra de 4,8% para 10,5% dos casos, com média de −87,3%.

Exigir liquidez mínima nas duas pernas melhora o líquido (p25 sobe de
−7,19% para 8,18% com ≥20 negócios) mas nunca chega aos 14,39% da ação, e
custa cobertura.

**Conclusão:** vender a perna de delta 15 financia parte do prêmio e cobra
por isso justamente onde a estratégia ganha dinheiro. Não usar.
