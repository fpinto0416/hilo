# -*- coding: utf-8 -*-
"""
Walk-Forward HiLo (somente WF) — selecao do hilo de MAIOR PNL ACUMULADO
ate a data, com rebalanceamento ANUAL


Walk-forward anual:
- Na primeira data de negociacao do mes definido em "meses_selecao"
  (default: MAIO), recalcula qual hilo tem o maior resultado acumulado
  desde o inicio da amostra ATE aquela data (sem look-ahead) e aplica
  esse hilo a partir da barra seguinte, vigente ate a proxima selecao.

Selecao por pnl acumulado:
- criterio unico: argmax do pnl acumulado em R$ de cada hilo, janela
  EXPANSIVA (todo o historico disponivel, sem esquecimento).
- todos os hilos operam com notional fixo de "montante_inicial", entao
  o pnl acumulado em R$ e diretamente comparavel entre eles.
- ATENCAO: por ser expansiva e sem decaimento, a estatistica fica cada
  vez mais rigida conforme o historico cresce. A coluna
  Qtd_HiLos_Distintos no resumo mede esse congelamento.

Construcao da curva do WF:
- o encadeamento entre hilos e feito pelo PNL DIARIO EM R$ de cada hilo,
  nunca pelo pct_change da curva acumulada. Cada backtest opera com
  notional fixo de "montante_inicial", entao pnl/montante_inicial e o
  retorno sobre o capital alocado, invariante ao nivel acumulado da
  curva daquele hilo.
- "modo_composicao" controla apenas como a curva e montada a partir
  desse pnl ("composto" ou "aditivo"). A serie de retornos usada em
  Vol_AA_WF e Sharpe_WF e a mesma nos dois modos.

Metricas do WF a partir da 1a vigencia:
- Rent_Total_WF, Rent_AA_WF, Drawdown_WF, Vol_AA_WF e Sharpe_WF sao
  calculados apenas sobre o periodo efetivamente investido.

Filtro adicional:
- a selecao so comeca apos "dias_minimos_selecao" barras do inicio
  do backtest (padrao: 1000); antes disso a estrategia fica flat.

Autor: Fabio Pinto
"""

import os
import warnings
import numpy as np
import pandas as pd
from scipy import stats

# #########################################################################
#                       >>>  ESCOLHA PRINCIPAL  <<<
#
# Como o hilo e escolhido a cada rebalanceamento anual.
#
# A selecao tem DOIS ESTAGIOS:
#   1o) triagem: os 10 hilos de MENOR p-valor unilateral, entre os que tem
#       t > 0 e historico minimo. Este estagio nao muda.
#   2o) desempate: entre esses 10 finalistas, vence o de maior valor da
#       metrica escolhida ABAIXO. E aqui que voce decide.
#
# Troque a linha METRICA_HILO para uma das quatro:
#
#   "expec"          ESPERANCA MATEMATICA em R$ por operacao = (Sg + Sl) / N.
#                    E o numero que se compara direto com o custo de
#                    transacao: esperanca de R$ 77 = suporta 77 bps por
#                    operacao. Foi o criterio do codigo antigo.
#
#   "payoff"         GANHO MEDIO / |PERDA MEDIA|. Mede so o TAMANHO relativo
#                    dos trades e IGNORA a taxa de acerto.
#                    ATENCAO: payoff alto nao significa lucro. Com acerto p,
#                    o equilibrio exige payoff = (1-p)/p. Em teste, este
#                    criterio escolheu hilos de esperanca NEGATIVA em 4 de 80
#                    selecoes e derrubou a esperanca mediana de R$ 25 para
#                    R$ 5. Se usar, acompanhe a coluna
#                    Qtd_Selecoes_Expec_Negativa no WF_Resumo.
#
#   "payoff_ajustado"  PAYOFF DESCONTADA A TENDENCIA DO COMPRIMENTO DO HILO.
#                    O payoff cresce mecanicamente com a janela — hilo longo
#                    segura mais tempo, entao o ganho medio sobe e a
#                    frequencia cai. Medido na sua base:
#                    Spearman(comprimento, payoff) = +0.84, positivo em 91%
#                    dos ativos. Ou seja, argmax(payoff) puro e quase
#                    equivalente a "use o hilo mais longo" — a metrica quase
#                    nao carrega informacao sobre o ativo.
#                    Aqui regride-se payoff sobre log(comprimento) usando
#                    todos os hilos elegiveis NAQUELA data e usa-se o RESIDUO
#                    padronizado: quanto o hilo entrega de payoff ACIMA do
#                    esperado para uma janela daquele tamanho. Preserva a sua
#                    tese de assimetria (ganho longo x perda curta) sem
#                    confundi-la com o efeito mecanico da janela.
#
#   "profit_factor"  SOMA DOS GANHOS / |SOMA DAS PERDAS| = payoff * p/(1-p).
#                    E o payoff corrigido pela frequencia. PF > 1 equivale a
#                    esperanca positiva, entao nunca escolhe hilo perdedor.
#                    Meio-termo entre os dois de cima.
#
# (a variavel de ambiente HILO_METRICA_ESTAGIO2 sobrepoe esta linha, se
#  estiver definida — util para rodar as tres e comparar sem editar o arquivo)
# #########################################################################

METRICA_HILO = "payoff"

# #########################################################################


warnings.filterwarnings("ignore", category=FutureWarning)

# =========================
# PARAMETROS
# =========================
montante_inicial = 10000
hilo_max = 100
hilo_min = 2
# so comeca a selecionar o melhor hilo apos esta quantidade de barras (pregoes)
dias_minimos_selecao = 1000

# mes de rebalanceamento do walk-forward (periodicidade ANUAL): maio
meses_selecao = [5]

# forma de construir a curva de capital do walk-forward:
# "composto" -> posicao redimensionada ao patrimonio corrente
#               curva = montante_inicial * cumprod(1 + pnl/montante_inicial)
#               comparavel ao buy and hold, nao pode ficar negativa
# "aditivo"  -> notional fixo de montante_inicial, fiel ao backtest de cada
#               hilo: curva = montante_inicial + cumsum(pnl)
#               pode ficar negativa (perda acumulada > capital inicial)
# em AMBOS os modos a serie de retornos e a mesma: pnl/montante_inicial.
modo_composicao = os.environ.get("HILO_MODO_COMPOSICAO", "composto")

# reamostragens do bootstrap de blocos usado na aba "p valor"
n_boot_pvalor = int(os.environ.get("HILO_N_BOOT", "2000"))

# tamanho (em anos) dos blocos do teste de estabilidade na aba "p valor"
anos_por_bloco_pvalor = int(os.environ.get("HILO_ANOS_BLOCO", "5"))

# ---- camada de CARTEIRA (selecao de ativos em walk-forward) ----
# esperanca minima (em multiplos de R, mesma escala de Esperanca_WF) para o
# ativo entrar na carteira no rebalanceamento
limiar_esperanca_carteira = float(os.environ.get("HILO_LIMIAR_ESPERANCA", "0.10"))
# minimo de operacoes encerradas para a esperanca do ativo ser confiavel
operacoes_minimas_carteira = int(os.environ.get("HILO_OPS_MIN_CARTEIRA", "20"))
# janelas moveis (em pregoes) avaliadas no resumo da carteira
janelas_carteira = [int(x) for x in
                    os.environ.get("HILO_JANELAS", "30,60,90,180,250").split(",")]

# minimo de barras de historico para um hilo ser elegivel na selecao
barras_minimas_hilo = int(os.environ.get("HILO_BARRAS_MIN", "252"))

# SELECAO EM DOIS ESTAGIOS
# 1o) triagem por significancia: os "n_finalistas" hilos de MENOR p unilateral
#     entre os que tem t > 0;
# 2o) entre esses finalistas, escolhe o de MAIOR ESPERANCA por operacao.
# Rationale: p/t medem confianca de que o retorno e positivo, mas ignoram
# quantas operacoes foram precisas para chegar la. A esperanca em R$ por
# operacao e o que se compara com o custo de transacao. O 1o estagio impede
# que a esperanca escolha um hilo de poucas operacoes sortudas; o 2o impede
# que o t escolha um hilo de giro alto e margem minima por trade.
n_finalistas_selecao = int(os.environ.get("HILO_N_FINALISTAS", "10"))

# metrica do 2o estagio (desempate entre os finalistas).
# O valor vem do painel METRICA_HILO no topo do arquivo; a variavel de
# ambiente HILO_METRICA_ESTAGIO2 sobrepoe, se definida.
#   "payoff"        -> ganho medio / |perda media|. Mede so o TAMANHO relativo
#                      dos trades; ignora a taxa de acerto. Tende a escolher
#                      hilos LONGOS (poucos trades, grandes) — efeito oposto ao
#                      do pnl acumulado, que puxava para hilos curtos.
#                      ATENCAO: payoff alto nao implica lucro. Com acerto p, o
#                      equilibrio exige payoff = (1-p)/p.
#   "profit_factor" -> soma dos ganhos / |soma das perdas| = payoff * p/(1-p).
#                      E o payoff corrigido pela frequencia; PF > 1 equivale a
#                      esperanca positiva.
#   "expec"         -> esperanca em R$ por operacao = (Sg + Sl) / N.
metrica_estagio2 = os.environ.get("HILO_METRICA_ESTAGIO2", METRICA_HILO)
if metrica_estagio2 not in ("expec", "payoff", "payoff_ajustado", "profit_factor"):
    raise ValueError(
        f"METRICA_HILO invalida: {metrica_estagio2!r}. Use 'expec', "
        "'payoff', 'payoff_ajustado' ou 'profit_factor'."
    )

# minimo de hilos com historico suficiente para estimar a tendencia
# payoff x log(comprimento) em "payoff_ajustado". Abaixo disso, usa payoff bruto.
minimo_hilos_ajuste = int(os.environ.get("HILO_MIN_AJUSTE", "20"))

# ---- simulacao de carteiras aleatorias (aba Carteiras_Aleatorias) ----
tamanhos_carteira_simulacao = [int(x) for x in
    os.environ.get("HILO_TAMANHOS_CARTEIRA", "10,20,30,50").split(",")]
n_simulacoes_carteira = int(os.environ.get("HILO_N_SIMULACOES", "2000"))
custos_bps_simulacao = [int(x) for x in
    os.environ.get("HILO_CUSTOS_BPS", "0,20,30,50").split(",")]
semente_simulacao = int(os.environ.get("HILO_SEMENTE", "42"))
# hilo fixo avaliado como referencia e hilo com que se compara
hilo_referencia_simulacao = int(os.environ.get("HILO_REFERENCIA", "75"))
hilo_comparacao_simulacao = int(os.environ.get("HILO_COMPARACAO", "20"))

# ---- janelas moveis com HILO FIXO (aba Janelas_Hilo_Fixo) ----
hilos_fixos_janelas = [int(x) for x in
    os.environ.get("HILO_FIXOS_JANELAS", "50,70,90").split(",")]
tamanhos_janelas = [int(x) for x in
    os.environ.get("HILO_TAMANHOS_JANELAS", "30,50").split(",")]
n_simulacoes_janelas = int(os.environ.get("HILO_N_SIM_JANELAS", "500"))
custo_bps_janelas = float(os.environ.get("HILO_CUSTO_JANELAS", "30"))
# CDI anual creditado ao caixa ocioso na variante LongOnly+CDI
cdi_aa_longonly = float(os.environ.get("HILO_CDI_AA", "10.0"))
# fracao de ativos comprados abaixo da qual a carteira e considerada desinvestida
limiar_exposicao_lacuna = float(os.environ.get("HILO_LIMIAR_EXPOSICAO", "0.10"))
# carteiras aleatorias para a aba LongOnly_Subamostras
tamanhos_carteira_longonly = [int(x) for x in
    os.environ.get("HILO_TAMANHOS_LONGONLY", "20,50").split(",")]
n_simulacoes_longonly = int(os.environ.get("HILO_N_SIM_LONGONLY", "500"))

# ---- RECORTE DE PERIODO ----
# Descarta barras anteriores a esta data ANTES de qualquer calculo. Serve para
# testar se um resultado depende de um evento unico: rodar com "2009-01-01"
# remove a crise de 2008, onde o long-only sai do mercado e economiza metade
# do drawdown do buy-and-hold. Se a vantagem sumir, ela vinha de uma
# observacao, nao de um padrao.
# ATENCAO: o corte reduz o historico disponivel, entao ativos podem deixar de
# atingir o minimo de barras e sair da amostra. O log informa quantos.
_di = os.environ.get("HILO_DATA_INICIO", "").strip()
data_inicio_analise = pd.Timestamp(_di) if _di else None
_df_ = os.environ.get("HILO_DATA_FIM", "").strip()
data_fim_analise = pd.Timestamp(_df_) if _df_ else None

# ---- SANIDADE DE DADOS ----
# Variacao diaria de preco acima da qual a serie e considerada SUSPEITA
# (desdobramento/bonificacao nao ajustado). Uma acao liquida nao anda 50% em
# um pregao; quando anda, quase sempre e artefato da base.
# Um unico ativo assim destroi qualquer analise agregada: BRKM5 apareceu com
# Expec_Mat de -11.631 sobre notional de 10.000 (perda de 116% do capital POR
# OPERACAO) e invertia de +R$1,9mi para -R$1,9mi entre o hilo 50 e o 70.
limiar_var_diaria_suspeita = float(os.environ.get("HILO_LIMIAR_VAR_DIARIA", "0.50"))
# se True, ativos suspeitos ficam de fora das analises AGREGADAS
# (Hilos_Agregado, Carteiras_Aleatorias, Janelas_Hilo_Fixo). Eles continuam
# nas abas por ativo, marcados, para nao sumirem sem aviso.
excluir_suspeitos_agregados = os.environ.get("HILO_EXCLUIR_SUSPEITOS", "1") == "1"

# minimo de operacoes ENCERRADAS para a esperanca do hilo ser confiavel.
# Sem isso, um hilo longo com 4 trades entra no top-10 pelo t (calculado sobre
# retornos diarios, onde n e grande) e vence por uma esperanca de 4 amostras.
operacoes_minimas_hilo = int(os.environ.get("HILO_OPS_MIN", "20"))

# p-valor unilateral maximo aceito para ficar posicionado.
# None = sempre escolhe o melhor hilo, mesmo sem evidencia (comparavel ao
# criterio anterior). Ex.: 0.10 = fica FLAT quando nenhum hilo atinge p<=0.10.
_pmax = os.environ.get("HILO_P_MAXIMO", "").strip()
p_maximo_selecao = float(_pmax) if _pmax else None

# exige t > 0 para o hilo ser elegivel. Quando nenhum hilo tem t > 0, a
# estrategia fica FLAT ate a proxima data de selecao, em vez de operar o
# "menos ruim" de um lote inteiramente ruim.
# Equivale a p_maximo_selecao = 0.5, ja que p_unilateral = 1 - Phi(t).
exigir_t_positivo = os.environ.get("HILO_EXIGIR_T_POSITIVO", "1") == "1"

# o que fazer quando NENHUM hilo passa nos filtros:
#   "repetir" -> mantem o hilo da selecao anterior; se nao houver anterior,
#                usa hilo_fallback_inicial. A estrategia fica sempre posicionada.
#   "flat"    -> sai do mercado ate a proxima data de selecao.
acao_sem_candidato = os.environ.get("HILO_SEM_CANDIDATO", "repetir")

# hilo usado quando nao ha candidato E nao existe selecao anterior
hilo_fallback_inicial = int(os.environ.get("HILO_FALLBACK_INICIAL", "20"))

dados_base = os.environ.get("HILO_DADOS_BASE", r"C:\AI_Sandbox\projeto_MIA\projeto_MIA26\database")
arquivo_saida = os.environ.get("HILO_ARQUIVO_SAIDA", "saidas_wf_hilo.xlsx")

_tickers_env = os.environ.get("HILO_TICKERS", "").strip()
if _tickers_env:
    TICKERS = [t.strip() for t in _tickers_env.split(",") if t.strip()]
else:
    TICKERS = [
        "BOVA11", "BBAS3", "PETR4", "ITUB4", "SMAL11",
        "CSNA3", "BBDC4", "VALE3", "CSAN3", "ITSA4",
        "TAEE11", "B3SA3", "SUZB3", "LREN3", "TIMS3",
        "VAMO3", "MGLU3", "POMO4", "JHSF3", "ISAE4",
        "ABEV3", "EZTC3", "SBSP3", "BRAV3", "WEGE3",
        "CSMG3", "BBSE3", "EQTL3", "COGN3", "EMBJ3",
        "CMIG4", "RENT3", "DIRR3", "MRVE3", "RAIZ4",
        "SIMH3", "AXIA3", "BRKM5", "CXSE3", "EGIE3",
        "AURA33", "BPAC11", "VBBR3", "RAIL3", "ALOS3",
        "RADL3", "ECOR3", "KLBN11", "IRBR3", "GGBR4",
        "VIVT3", "AZZA3", "PSSA3", "ITUB3", "USIM5",
        "CMIN3", "IGTI11", "ENEV3", "FLRY3", "CEAB3",
        "GMAT3", "XPBR31", "TOTS3", "IBOV11", "BRAP4",
        "HAPV3", "MOVI3", "AUAU3", "SLCE3", "PRIO3",
        "BBDC3", "CVCB3", "QUAL3", "CPFE3", "SMFT3",
        "BEEF3", "MBRF3", "GOAU4", "NATU3", "VIVA3",
        "AMBP3", "CYRE3", "RDOR3", "ORVR3", "BRSR6",
        "UGPA3", "HYPE3", "RECV3", "MULT3", "WIZC3",
        "RAPT4", "PCAR3", "ROXO34", "GRND3", "CPLE3",
        "POSI3", "UNIP6", "ENGI11", "YDUQ3", "FESA4",
    ]

# =========================
# FUNCOES AUXILIARES
# =========================
def calculate_hilo(df, n):
    hilo_high = df["High"].rolling(window=n).mean().shift(2)
    hilo_low = df["Low"].rolling(window=n).mean().shift(2)
    return hilo_high, hilo_low

def annualize_return(total_return, n_bars, bars_per_year=252):
    if n_bars <= 0:
        return np.nan
    base = 1 + total_return
    if base <= 0:
        return np.nan
    return ((base ** (bars_per_year / n_bars)) - 1) * 100

def preparar_dados(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, index_col=0, parse_dates=True)

    if df.empty:
        return None

    df.columns = [str(c).strip() for c in df.columns]

    colunas_necessarias = ["Open", "High", "Low", "Close"]
    for col in colunas_necessarias:
        if col not in df.columns:
            raise ValueError(f"Coluna ausente no arquivo: {col}")

    if "Volume" in df.columns:
        df = df.drop(columns=["Volume"])

    df = df.sort_index()
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    df = df[~df.index.duplicated(keep="first")].copy()

    # recorte de periodo antes de qualquer calculo (inclusive do holding,
    # que passa a comecar na nova primeira barra — comparacao justa)
    if data_inicio_analise is not None:
        df = df[df.index >= data_inicio_analise]
    if data_fim_analise is not None:
        df = df[df.index <= data_fim_analise]

    if df.empty:
        return None

    # precisa de historico suficiente para (a) formar o hilo mais longo e
    # (b) atingir dias_minimos_selecao antes que exista qualquer selecao
    if len(df) < hilo_max + (dias_minimos_selecao or 0) + 5:
        return None

    # diagnostico de dado sujo: maior variacao diaria de preco da serie
    var_d = df["Close"].pct_change().abs()
    df.attrs["max_var_diaria"] = float(var_d.max()) if var_d.notna().any() else np.nan
    df.attrs["data_max_var"] = (var_d.idxmax() if var_d.notna().any() else pd.NaT)
    df.attrs["n_barras_extremas"] = int((var_d > limiar_var_diaria_suspeita).sum())

    qtd_holding = montante_inicial / df["Close"].iloc[0]
    df["holding"] = df["Close"] * qtd_holding

    return df

def selecionar_amostra_backtest(df_base):
    # sem reserva de barras finais: o backtest usa a amostra inteira,
    # ate a ultima barra disponivel.
    df = df_base.copy()

    if df.empty or len(df) < hilo_max + (dias_minimos_selecao or 0):
        return None

    return df

# =========================
# BACKTEST VETORIZADO (uso interno da selecao)
# =========================
def rodar_backtest_hilo_vetorizado(df_base, n_hilo):
    """
    Backtest de um hilo. Uso interno: retorna apenas a curva de capital
    e as colunas de operacoes necessarias para a selecao e para as
    metricas do walk-forward.
    """
    df = selecionar_amostra_backtest(df_base)

    if df is None or df.empty:
        return None

    df["Hi"], df["Lo"] = calculate_hilo(df, n_hilo)

    df["decision_raw"] = 0
    df.loc[df["Close"].shift(1) > df["Hi"], "decision_raw"] = 1
    df.loc[df["Close"].shift(1) < df["Lo"], "decision_raw"] = -1

    df["decision"] = df["decision_raw"].replace(0, np.nan).ffill().fillna(0)

    df["decision_shift"] = df["decision"].shift(1).fillna(0)
    df["houve_troca"] = df["decision"] != df["decision_shift"]

    df["close_diff"] = df["Close"].diff().fillna(0)

    df["posicao"] = 0.0
    mask_entrada = df["houve_troca"] & (df["decision"] != 0)

    df.loc[mask_entrada, "posicao"] = (
        montante_inicial * df.loc[mask_entrada, "decision"] / df.loc[mask_entrada, "Close"]
    )

    df["posicao"] = df["posicao"].replace(0, np.nan).ffill().fillna(0.0)
    df.loc[df["decision"] == 0, "posicao"] = 0.0

    # pnl da barra vem da posicao carregada DA BARRA ANTERIOR
    df["pnl"] = df["posicao"].shift(1).fillna(0.0) * df["close_diff"]
    df["resultado_carteira"] = montante_inicial + df["pnl"].cumsum()

    # trade identificado pela posicao efetivamente carregada na barra
    df["posicao_carregada"] = df["posicao"].shift(1).fillna(0.0)
    df["trade_decision"] = np.sign(df["posicao_carregada"]).astype(int)

    df["trade_decision_shift"] = df["trade_decision"].shift(1).fillna(0)
    df["trade_troca"] = df["trade_decision"] != df["trade_decision_shift"]
    df["trade_id"] = df["trade_troca"].cumsum().astype(int)
    df.loc[df["trade_decision"] == 0, "trade_id"] = np.nan

    return df[["resultado_carteira", "trade_id", "trade_decision", "pnl", "holding"]]

# =========================
# WALK-FORWARD: SELECAO A CADA 4 MESES (JAN/MAI/SET)
# =========================
def primeiras_datas_meses(index, meses):
    """Retorna a primeira data de negociacao de cada mes de selecao."""
    idx = pd.DatetimeIndex(index)
    df_datas = pd.DataFrame({"data": idx, "ano": idx.year, "mes": idx.month})
    df_datas = df_datas[df_datas["mes"].isin(meses)]
    primeiras = df_datas.groupby(["ano", "mes"])["data"].min().sort_values()
    return list(primeiras)

def metricas_operacoes_wf(ops_por_hilo, selecoes, idx):
    """
    Reconstroi as operacoes da estrategia walk-forward.

    Dentro de cada trecho de vigencia, agrupa as operacoes do hilo
    vigente (coluna trade_id do backtest daquele hilo), clipadas ao
    trecho, e soma o pnl. Operacoes que cruzam a fronteira de um
    trecho sao contabilizadas no trecho seguinte (quando a posicao
    esta efetivamente carregada).
    """
    frames = []

    for i, sel in enumerate(selecoes):
        hilo = sel["hilo"]
        if hilo not in ops_por_hilo:
            continue

        pos_ini = sel["pos"] + 1
        pos_fim = sel["pos_fim"]
        if pos_ini > pos_fim:
            continue

        df_ops = ops_por_hilo[hilo]
        trecho = df_ops.iloc[pos_ini:pos_fim + 1]
        trecho = trecho[trecho["trade_decision"] != 0]

        if trecho.empty:
            continue

        grp = (
            trecho.groupby("trade_id", as_index=False)
            .agg(
                decision=("trade_decision", "last"),
                data_inicio=("Data", "first"),
                data_fim=("Data", "last"),
                duracao_candles=("pnl", "size"),
                pnl_operacao=("pnl", "sum"),
            )
            .rename(columns={"trade_id": "operacao"})
        )
        grp["hilo"] = int(hilo)
        grp["data_selecao"] = sel["data_sel"]
        frames.append(grp)

    if len(frames) == 0:
        return pd.DataFrame(columns=[
            "operacao", "decision", "data_inicio", "data_fim",
            "duracao_candles", "pnl_operacao", "hilo", "data_selecao"
        ])

    return pd.concat(frames, ignore_index=True)

def _rent_trecho_curva(curva, pos_ini, pos_fim):
    """
    Rentabilidade de um trecho a partir da propria curva de capital.

    Substitui o antigo prod(1 + ret) - 1, que so era valido no modo
    composto. Retorna NaN se a base do trecho nao for positiva (possivel
    no modo aditivo, quando a perda acumulada supera o capital inicial).
    """
    base = float(curva.iloc[pos_ini - 1]) if pos_ini > 0 else float(montante_inicial)
    if not np.isfinite(base) or base <= 0:
        return np.nan
    fim = float(curva.iloc[pos_fim])
    if not np.isfinite(fim):
        return np.nan
    return fim / base - 1.0


def _sem_candidato(motivo, data_sel, pos, n_i, t_val, hilo_anterior,
                   decisoes, hilo_vigente, idx, stats_hilo, col_idx):
    """
    Decide o que fazer quando nenhum hilo passa nos filtros da data.

    acao_sem_candidato == "repetir": mantem o hilo anterior; na primeira
    selecao, quando nao existe anterior, usa hilo_fallback_inicial.
    A estrategia permanece SEMPRE POSICIONADA.

    ATENCAO: repetir significa continuar operando um hilo que acabou de
    falhar no criterio que o elegeu. As estatisticas registradas no log
    (t, p, Sharpe) sao as do hilo REPETIDO na data — nao as do vencedor,
    que nao existe. Espere ver t <= 0 nessas linhas: e o ponto.

    Retorna o hilo que passa a valer (para virar o "anterior" da proxima).
    """
    if acao_sem_candidato == "flat":
        decisoes.append({"data_sel": data_sel, "pos": pos, "hilo": None,
                         "origem": "flat", "motivo": motivo})
        if pos + 1 < len(idx):
            hilo_vigente.iloc[pos + 1:] = np.nan
        return hilo_anterior

    if hilo_anterior is not None:
        hilo_usar, origem = int(hilo_anterior), "repetido"
    else:
        # primeira selecao sem candidato: recorre ao hilo default.
        # Se ele nao existir na grade, usa o mais proximo disponivel.
        disponiveis = np.array(sorted(col_idx.keys()))
        if hilo_fallback_inicial in col_idx:
            hilo_usar = int(hilo_fallback_inicial)
        else:
            hilo_usar = int(disponiveis[np.argmin(np.abs(disponiveis - hilo_fallback_inicial))])
        origem = "fallback_inicial"

    st = stats_hilo(hilo_usar, n_i, t_val, pos)
    if st is None:
        decisoes.append({"data_sel": data_sel, "pos": pos, "hilo": None,
                         "origem": "flat", "motivo": motivo + " | hilo indisponivel"})
        if pos + 1 < len(idx):
            hilo_vigente.iloc[pos + 1:] = np.nan
        return hilo_anterior

    decisoes.append({
        "data_sel": data_sel,
        "pos": pos,
        "hilo": hilo_usar,
        "p_escolhido": st["p"],
        "t_escolhido": st["t"],
        "sharpe_escolhido": st["sharpe"],
        "n_barras_escolhido": st["n"],
        "pnl_acum_escolhido": np.nan,
        "qtd": 0,
        "origem": origem,
        "motivo": motivo,
    })

    if pos + 1 < len(idx):
        hilo_vigente.iloc[pos + 1:] = float(hilo_usar)
    return hilo_usar


def rodar_walkforward_anual(ticker, pnl_por_hilo_df, ops_por_hilo):
    """
    Walk-forward com rebalanceamento ANUAL.

    Na primeira data de negociacao dos meses em "meses_selecao":
      1) calcula, para CADA hilo, o p-valor UNILATERAL do seu retorno
         desde o inicio da amostra ate aquela data (janela expansiva);
      2) TRIAGEM: separa os "n_finalistas" hilos de MENOR p-valor entre
         os elegiveis (t > 0, historico e numero de operacoes minimos);
      3) ESCOLHA: entre esses finalistas, pega o de MAIOR valor da metrica
         definida em "metrica_estagio2" (default: PAYOFF), calculada sobre
         as operacoes encerradas ate a data;
      4) aplica o hilo escolhido a partir da BARRA SEGUINTE, vigente
         ate a proxima data de selecao.

    POR QUE DOIS ESTAGIOS: p/t medem a confianca de que o retorno e
    positivo, mas ignoram quantas operacoes foram precisas para chegar la —
    o argmax de t tende a escolher hilos curtos, de giro alto e margem
    minima por trade, que morrem com custo de transacao. A metrica do 2o
    estagio corrige isso. A triagem por p, por sua vez, impede que ela
    premie um hilo de poucas operacoes sortudas; operacoes_minimas_hilo
    reforca.

    CUIDADO COM "payoff" NO 2o ESTAGIO: payoff mede so o tamanho relativo
    dos trades e ignora a taxa de acerto — payoff alto NAO implica lucro.
    Com acerto p, o equilibrio exige payoff = (1-p)/p. O filtro t > 0 do 1o
    estagio protege bastante, mas t vem de retornos DIARIOS e a esperanca de
    trades FECHADOS, entao os dois podem divergir. A coluna
    Qtd_Selecoes_Expec_Negativa no WF_Resumo conta quantas vezes isso
    aconteceu; se for > 0, considere "profit_factor", que e o payoff
    corrigido pela frequencia (PF > 1 equivale a esperanca positiva).

    A esperanca considera apenas operacoes ENCERRADAS ate a data: o pnl de
    um trade ainda aberto nao entra (seria vazamento parcial de informacao
    e distorceria a media por operacao).

    POR QUE UNILATERAL, E NAO O p_Padrao DA ABA "p valor":
    o p bilateral nao tem direcao — e igualmente baixo para um hilo que
    ganha de forma consistente e para um que PERDE de forma consistente.
    argmin do p bilateral selecionaria o maior |t|, e o pior hilo da
    amostra tem |t| tao alto quanto o melhor. Aqui H0 e "media <= 0" e
    p = 1 - Phi(t), entao um hilo perdedor tem p proximo de 1 e nunca e
    escolhido.

    EQUIVALENCIA QUE VALE SABER: como todos os hilos compartilham a mesma
    janela, p_unilateral = 1 - Phi(t) e t = Sharpe * sqrt(n). Ordenar por
    p unilateral e, na pratica, ordenar por SHARPE. O criterio e
    risco-ajustado: ao contrario do pnl acumulado, nao se deixa dominar
    por um unico trade sortudo. O p-valor e a escala de leitura, o Sharpe
    e o que de fato decide.

    Usa o t convencional, nao Newey-West: simulacao mostrou os dois
    praticamente identicos nesta estrategia, e o NW custaria 99 hilos x
    N datas de selecao por ativo.

    FILTRO t > 0 (exigir_t_positivo, ligado por default): um hilo so e
    elegivel se seu t acumulado ate a data for positivo. Se nenhum for, a
    estrategia fica FLAT ate a proxima data de selecao, em vez de comprar o
    menos ruim de um lote inteiramente ruim. Equivale a p_maximo_selecao =
    0.5, ja que p_unilateral = 1 - Phi(t). Essas janelas aparecem no
    WF_Trocas com HiLo_Escolhido vazio e Motivo_Flat preenchido.

    SEM CANDIDATO (acao_sem_candidato = "repetir", default): quando nenhum
    hilo passa nos filtros, MANTEM o hilo da selecao anterior; se nao houver
    anterior, usa hilo_fallback_inicial (default 20). A estrategia fica
    sempre posicionada. Use "flat" para sair do mercado nesses casos.

    Consequencia a ter em mente: repetir significa seguir operando um hilo
    que acabou de falhar no criterio que o elegeu. As colunas t/p/Sharpe do
    WF_Trocas nessas linhas sao as do hilo REPETIDO, entao devem aparecer com
    t <= 0. Origem_Selecao distingue "criterio", "repetido" e
    "fallback_inicial".

    Filtro: datas de selecao anteriores a "dias_minimos_selecao" barras
    do inicio do backtest sao ignoradas (estrategia fica flat).

    Metricas: apenas o periodo efetivamente investido (da primeira
    data de vigencia ate o fim da amostra).
    """
    if pnl_por_hilo_df is None or pnl_por_hilo_df.empty:
        return None, None, None

    # pnl_por_hilo_df: pnl DIARIO em R$ de cada hilo (notional fixo de
    # montante_inicial). Nao usar curva acumulada aqui: pct_change de curva
    # aditiva encadeia percentuais calculados sobre bases acumuladas
    # diferentes a cada troca de hilo, e explode se a curva cruzar zero.
    pnl_por_hilo_df = pnl_por_hilo_df.sort_index()
    idx = pnl_por_hilo_df.index

    pnl_lim = pnl_por_hilo_df.fillna(0.0)
    ret_lim = pnl_lim / float(montante_inicial)   # retorno sobre o notional fixo

    # somas acumuladas para obter media/desvio/t em qualquer data em O(1).
    # As barras anteriores a primeira operacao de um hilo tem pnl = 0, entao
    # nao afetam soma nem soma dos quadrados — afetam apenas a contagem n,
    # corrigida abaixo por "primeira_barra".
    S1 = ret_lim.cumsum()
    S2 = (ret_lim ** 2).cumsum()

    # primeira barra em que cada hilo de fato operou (hilos longos demoram
    # mais para aquecer; contar as barras mortas infla n e o t).
    tem_op = ret_lim.ne(0.0)
    primeira_barra = tem_op.values.argmax(axis=0).astype(float)
    primeira_barra[~tem_op.any(axis=0).values] = np.nan

    col_idx = {int(c): i for i, c in enumerate(pnl_por_hilo_df.columns)}
    hilos_arr = np.array([float(c) for c in pnl_por_hilo_df.columns])
    log_hilo = np.log(hilos_arr)

    # Esperanca acumulada por hilo, barra a barra.
    # A esperanca so pode considerar operacoes ENCERRADAS: o pnl de um trade
    # ainda aberto na data de selecao nao entra. Por isso o pnl de cada trade
    # e lancado inteiro na sua barra de FECHAMENTO, e nao distribuido pelas
    # barras em que o trade esteve vivo.
    forma = (len(idx), len(col_idx))
    pnl_fechado = np.zeros(forma); ops_fechadas = np.zeros(forma)
    ganho_soma = np.zeros(forma); ganho_cont = np.zeros(forma)
    perda_soma = np.zeros(forma); perda_cont = np.zeros(forma)
    pos_de_data = {d: i for i, d in enumerate(idx)}

    for hilo_c, jj in col_idx.items():
        g = ops_por_hilo.get(hilo_c)
        if g is None or g.empty or "trade_id" not in g.columns:
            continue
        gv = g.dropna(subset=["trade_id"])
        if gv.empty:
            continue
        agg = gv.groupby("trade_id").agg(pnl=("pnl", "sum"), data_fim=("Data", "last"))
        for pnl_t, dfim in zip(agg["pnl"].values, agg["data_fim"].values):
            ip = pos_de_data.get(pd.Timestamp(dfim))
            if ip is None:
                continue
            v = float(pnl_t)
            pnl_fechado[ip, jj] += v
            ops_fechadas[ip, jj] += 1.0
            if v > 0:
                ganho_soma[ip, jj] += v; ganho_cont[ip, jj] += 1.0
            elif v < 0:
                perda_soma[ip, jj] += v; perda_cont[ip, jj] += 1.0

    PNL_FECH = pnl_fechado.cumsum(axis=0)
    OPS_FECH = ops_fechadas.cumsum(axis=0)
    SG_FECH = ganho_soma.cumsum(axis=0);  NW_FECH = ganho_cont.cumsum(axis=0)
    SL_FECH = perda_soma.cumsum(axis=0);  NL_FECH = perda_cont.cumsum(axis=0)

    datas_selecao = primeiras_datas_meses(idx, meses_selecao)

    hilo_vigente = pd.Series(np.nan, index=idx, dtype=float)
    decisoes = []          # TODA data de selecao avaliada
    hilo_anterior = None   # ultimo hilo efetivamente adotado

    def _stats_hilo(col_hilo, n_i, t_val, pos):
        """Estatisticas do hilo indicado, para registro no log de trocas."""
        if col_hilo not in col_idx:
            return None
        jj = col_idx[col_hilo]
        tt = float(t_val[jj]) if np.isfinite(t_val[jj]) else np.nan
        nn = float(n_i[jj]) if np.isfinite(n_i[jj]) else np.nan
        return {
            "j": jj,
            "t": tt,
            "p": float(1.0 - stats.norm.cdf(tt)) if np.isfinite(tt) else np.nan,
            "n": nn,
            "sharpe": (float(tt / np.sqrt(nn) * np.sqrt(252.0))
                       if np.isfinite(tt) and np.isfinite(nn) and nn > 0 else np.nan),
        }

    for data_sel in datas_selecao:
        pos = idx.get_loc(data_sel)

        # FILTRO: so comeca a selecionar apos "dias_minimos_selecao" barras
        if dias_minimos_selecao is not None and dias_minimos_selecao > 0:
            if pos < dias_minimos_selecao:
                continue

        # estatisticas de cada hilo ATE a data de selecao (inclusive).
        # Usa .iloc[pos] — nao ha vazamento: a barra de selecao ja fechou.
        n_i = pos - primeira_barra + 1.0
        s1 = S1.iloc[pos].values
        s2 = S2.iloc[pos].values

        with np.errstate(invalid="ignore", divide="ignore"):
            media = s1 / n_i
            var = (s2 - (s1 ** 2) / n_i) / (n_i - 1.0)
            t_val = media / np.sqrt(var / n_i)

        # metricas de operacoes ENCERRADAS acumuladas ate a data
        ops_ac = OPS_FECH[pos]
        sg, nw_ = SG_FECH[pos], NW_FECH[pos]
        sl, nl_ = SL_FECH[pos], NL_FECH[pos]
        with np.errstate(invalid="ignore", divide="ignore"):
            expec = np.where(ops_ac > 0, PNL_FECH[pos] / ops_ac, np.nan)
            ganho_m = np.where(nw_ > 0, sg / np.where(nw_ > 0, nw_, np.nan), np.nan)
            perda_m = np.abs(np.where(nl_ > 0, sl / np.where(nl_ > 0, nl_, np.nan), np.nan))
            payoff_h = np.where(perda_m > 0, ganho_m / perda_m, np.nan)
            pfactor = np.where(sl != 0, sg / np.abs(np.where(sl != 0, sl, np.nan)), np.nan)

        if metrica_estagio2 == "payoff_ajustado":
            # PAYOFF AJUSTADO PELO COMPRIMENTO DO HILO.
            # payoff cresce mecanicamente com a janela: hilo longo segura a
            # posicao mais tempo, entao ganho medio sobe e a frequencia cai.
            # Medido na base do usuario: Spearman(comprimento, payoff) = +0.84.
            # argmax(payoff) puro e, na pratica, "use o hilo mais longo".
            #
            # Aqui a tendencia e removida: regride-se payoff sobre log(hilo)
            # usando TODOS os hilos com historico suficiente NAQUELA data, e a
            # metrica passa a ser o RESIDUO padronizado — quanto o hilo entrega
            # de payoff ACIMA do esperado para uma janela daquele tamanho.
            # A regressao usa so dados ate a data de selecao: sem look-ahead.
            base = (np.isfinite(payoff_h) & (ops_ac >= operacoes_minimas_hilo)
                    & (nw_ > 0) & (nl_ > 0))
            metrica2 = np.full(len(payoff_h), np.nan)
            if int(base.sum()) >= minimo_hilos_ajuste:
                b1, b0 = np.polyfit(log_hilo[base], payoff_h[base], 1)
                resid = payoff_h - (b0 + b1 * log_hilo)
                sd_r = float(np.nanstd(resid[base]))
                metrica2 = resid / sd_r if sd_r > 0 else resid
                inclinacao_ajuste = float(b1)
            else:
                # poucos hilos para estimar a tendencia: cai no payoff bruto
                metrica2 = payoff_h
                inclinacao_ajuste = np.nan
        elif metrica_estagio2 == "payoff":
            metrica2 = payoff_h
            inclinacao_ajuste = np.nan
        elif metrica_estagio2 == "profit_factor":
            metrica2 = pfactor
            inclinacao_ajuste = np.nan
        elif metrica_estagio2 == "expec":
            metrica2 = expec
            inclinacao_ajuste = np.nan
        else:
            raise ValueError(
                f"metrica_estagio2 invalida: {metrica_estagio2!r} (use "
                "'expec', 'payoff', 'payoff_ajustado' ou 'profit_factor')"
            )

        # ---- elegibilidade ----
        valido = (np.isfinite(t_val) & (n_i >= barras_minimas_hilo) & (var > 0)
                  & (ops_ac >= operacoes_minimas_hilo) & np.isfinite(metrica2))

        # exige evidencia de retorno POSITIVO. Sem isso, o argmax de t pega o
        # menos ruim de um lote todo ruim e fica comprado sem motivo.
        if exigir_t_positivo:
            valido = valido & (t_val > 0.0)

        # p-valor maximo, quando configurado, tambem e criterio de elegibilidade
        if p_maximo_selecao is not None:
            valido = valido & ((1.0 - stats.norm.cdf(t_val)) <= p_maximo_selecao)

        if not valido.any():
            motivo = "nenhum hilo elegivel (t > 0"
            motivo += f", >= {operacoes_minimas_hilo} ops"
            motivo += (f", p <= {p_maximo_selecao}" if p_maximo_selecao is not None else "")
            hilo_anterior = _sem_candidato(
                motivo + ")", data_sel, pos, n_i, t_val,
                hilo_anterior, decisoes, hilo_vigente, idx, _stats_hilo, col_idx)
            continue

        # ---- 1o estagio: os n_finalistas de MENOR p (= MAIOR t) ----
        cand = np.flatnonzero(valido)
        ordem_t = cand[np.argsort(-t_val[cand], kind="stable")]
        finalistas = ordem_t[:max(1, n_finalistas_selecao)]

        # ---- 2o estagio: entre os finalistas, MAIOR valor da metrica escolhida ----
        j = int(finalistas[int(np.argmax(metrica2[finalistas]))])

        hilo_escolhido = int(pnl_por_hilo_df.columns[j])
        t_escolhido = float(t_val[j])
        p_escolhido = float(1.0 - stats.norm.cdf(t_escolhido))
        n_escolhido = float(n_i[j])
        sharpe_escolhido = float(t_escolhido / np.sqrt(n_escolhido) * np.sqrt(252.0))
        expec_escolhido = float(expec[j])
        payoff_escolhido = float(payoff_h[j]) if np.isfinite(payoff_h[j]) else np.nan
        pf_escolhido = float(pfactor[j]) if np.isfinite(pfactor[j]) else np.nan
        acerto_escolhido = float(nw_[j] / ops_ac[j]) if ops_ac[j] > 0 else np.nan
        ops_escolhido = float(ops_ac[j])
        rank_t = int(np.flatnonzero(ordem_t == j)[0]) + 1   # posicao no ranking de t

        decisoes.append({
            "data_sel": data_sel,
            "pos": pos,
            "hilo": hilo_escolhido,
            "p_escolhido": p_escolhido,
            "t_escolhido": t_escolhido,
            "sharpe_escolhido": sharpe_escolhido,
            "n_barras_escolhido": n_escolhido,
            "pnl_acum_escolhido": float(pnl_lim.iloc[:pos + 1, j].sum()),
            "expec_escolhido": expec_escolhido,
            "payoff_escolhido": payoff_escolhido,
            "payoff_ajustado_escolhido": (float(metrica2[j])
                                          if metrica_estagio2 == "payoff_ajustado"
                                          else np.nan),
            "inclinacao_ajuste": inclinacao_ajuste,
            "pf_escolhido": pf_escolhido,
            "acerto_escolhido": acerto_escolhido,
            "ops_acum_escolhido": ops_escolhido,
            "rank_t_escolhido": rank_t,
            "qtd_finalistas": int(len(finalistas)),
            "qtd": int(valido.sum()),
            "origem": "criterio",
            "motivo": "",
        })
        hilo_anterior = hilo_escolhido

        # hilo novo vale a partir da barra seguinte a selecao
        if pos + 1 < len(idx):
            hilo_vigente.iloc[pos + 1:] = float(hilo_escolhido)

    # BUG CORRIGIDO: as fronteiras de vigencia tem que sair de TODAS as datas
    # de decisao, nao so das que escolheram um hilo. Se uma data foi flat, o
    # trecho da selecao anterior termina ALI — caso contrario as metricas de
    # operacoes contariam trades do hilo antigo durante a janela flat, e o
    # Rent_Trecho absorveria o periodo parado.
    for i, dec in enumerate(decisoes):
        dec["pos_fim"] = (decisoes[i + 1]["pos"] if i + 1 < len(decisoes)
                          else len(idx) - 1)

    selecoes = [d for d in decisoes if d["hilo"] is not None]
    flats = [d for d in decisoes if d["hilo"] is None]

    if len(selecoes) == 0:
        return None, None, None

    # pnl diario da estrategia = pnl em R$ do hilo vigente em cada barra
    pnl_estrategia = pd.Series(0.0, index=idx)
    cols = list(pnl_por_hilo_df.columns)
    col_pos = {c: i for i, c in enumerate(cols)}
    mask_valid = hilo_vigente.notna()

    if mask_valid.any():
        linhas = np.flatnonzero(mask_valid.values)
        colunas = np.array([col_pos[int(h)] for h in hilo_vigente[mask_valid]])
        valores = pnl_por_hilo_df.values[linhas, colunas]
        pnl_estrategia.iloc[linhas] = np.nan_to_num(valores, nan=0.0)

    # cada backtest individual opera com notional fixo de montante_inicial,
    # entao pnl/montante_inicial e o retorno sobre o capital alocado naquela
    # barra — invariante ao nivel acumulado da curva daquele hilo. E esta a
    # grandeza que pode ser encadeada entre hilos diferentes.
    ret_estrategia = pnl_estrategia / float(montante_inicial)

    if modo_composicao == "composto":
        # posicao redimensionada ao patrimonio corrente: pnl_real = pnl * E/M,
        # logo retorno = pnl/M. Curva nunca fica negativa, exceto se uma unica
        # barra perder mais de 100% — o que indica preco nao ajustado.
        extremos = (ret_estrategia <= -1.0) & mask_valid
        if bool(extremos.any()):
            datas_ruins = [str(d.date()) for d in idx[extremos.values][:5]]
            print(
                f"{ticker}: {int(extremos.sum())} barra(s) com retorno <= -100% "
                f"(ex.: {datas_ruins}). Provavel preco nao ajustado por "
                f"desdobramento/bonificacao. Ativo descartado."
            )
            return None, None, None
        curva = montante_inicial * (1.0 + ret_estrategia).cumprod()
    elif modo_composicao == "aditivo":
        # fiel ao backtest de cada hilo: notional fixo, pnl somado em R$.
        # Pode ficar negativa; isso agora e um resultado honesto da estrategia,
        # nao um artefato numerico de pct_change/cumprod.
        curva = montante_inicial + pnl_estrategia.cumsum()
    else:
        raise ValueError(
            f"modo_composicao invalido: {modo_composicao!r} "
            "(use 'composto' ou 'aditivo')"
        )

    # log de trocas com vigencia e retorno de cada trecho
    trocas = []
    for i, sel in enumerate(selecoes):
        pos_ini = sel["pos"] + 1
        pos_fim = sel["pos_fim"]

        if pos_ini > len(idx) - 1:
            data_ini, data_fim, dias, rent_trecho = pd.NaT, pd.NaT, 0, np.nan
        else:
            data_ini = idx[pos_ini]
            data_fim = idx[pos_fim]
            dias = pos_fim - pos_ini + 1
            rent_trecho = _rent_trecho_curva(curva, pos_ini, pos_fim)

        trocas.append({
            "Ativo": ticker,
            "Data_Selecao": sel["data_sel"],
            "HiLo_Escolhido": sel["hilo"],
            "Origem_Selecao": sel.get("origem", "criterio"),
            "Motivo": sel.get("motivo", ""),
            "p_Unilateral_Escolhido": sel["p_escolhido"],
            "t_Escolhido": sel["t_escolhido"],
            "Sharpe_AA_Escolhido": sel["sharpe_escolhido"],
            "N_Barras_Escolhido": sel["n_barras_escolhido"],
            "Payoff_Escolhido": sel.get("payoff_escolhido", np.nan),
            "Payoff_Ajustado_Escolhido": sel.get("payoff_ajustado_escolhido", np.nan),
            "Inclinacao_Payoff_vs_logHilo": sel.get("inclinacao_ajuste", np.nan),
            "ProfitFactor_Escolhido": sel.get("pf_escolhido", np.nan),
            "Taxa_Acerto_Escolhido": sel.get("acerto_escolhido", np.nan),
            "Expec_Escolhido": sel.get("expec_escolhido", np.nan),
            "Ops_Acum_Escolhido": sel.get("ops_acum_escolhido", np.nan),
            "Rank_t_Escolhido": sel.get("rank_t_escolhido", np.nan),
            "Qtd_Finalistas": sel.get("qtd_finalistas", np.nan),
            "Pnl_Acum_HiLo_Escolhido": sel["pnl_acum_escolhido"],
            "Qtd_Janelas_Avaliadas": sel["qtd"],
            "Data_Inicio_Vigencia": data_ini,
            "Data_Fim_Vigencia": data_fim,
            "Dias_Vigencia": dias,
            "Rent_Trecho": rent_trecho,
        })

    # janelas em que a estrategia ficou FORA do mercado por falta de evidencia.
    # Precisam aparecer: sem elas, uma sequencia de anos flat fica invisivel e
    # o Perc_Tempo_Investido no resumo parece inexplicavel.
    for dec in flats:
        pos_ini = dec["pos"] + 1
        pos_fim = dec["pos_fim"]
        trocas.append({
            "Ativo": ticker,
            "Data_Selecao": dec["data_sel"],
            "HiLo_Escolhido": np.nan,
            "Origem_Selecao": "flat",
            "Motivo": dec["motivo"],
            "Data_Inicio_Vigencia": idx[pos_ini] if pos_ini <= len(idx) - 1 else pd.NaT,
            "Data_Fim_Vigencia": idx[pos_fim] if pos_ini <= len(idx) - 1 else pd.NaT,
            "Dias_Vigencia": max(pos_fim - pos_ini + 1, 0),
            "Rent_Trecho": 0.0,
        })

    trocas_df = pd.DataFrame(trocas)
    if not trocas_df.empty:
        trocas_df = trocas_df.sort_values("Data_Selecao").reset_index(drop=True)

    # =====================================================
    # METRICAS DO WF: apenas o periodo efetivamente investido
    # =====================================================
    pos_primeira_vigencia = selecoes[0]["pos"] + 1
    if pos_primeira_vigencia > len(idx) - 1:
        pos_primeira_vigencia = len(idx) - 1

    data_inicio_wf = idx[pos_primeira_vigencia]
    data_fim_wf = idx[-1]

    ret_investido = ret_estrategia.iloc[pos_primeira_vigencia:]
    curva_investido = curva.iloc[pos_primeira_vigencia:]
    n_investido = len(ret_investido)

    # base = valor da curva na vespera da primeira vigencia
    base_wf = float(curva.iloc[pos_primeira_vigencia - 1]) if pos_primeira_vigencia > 0 else montante_inicial

    if not np.isfinite(base_wf) or base_wf <= 0:
        rent_total = np.nan
        rent_aa = np.nan
    else:
        rent_total = float(curva_investido.iloc[-1] / base_wf - 1.0)
        rent_aa = annualize_return(rent_total, n_investido, 252) if rent_total > -1 else np.nan

    # cummax e sempre >= base_wf > 0 porque a curva fica flat em
    # montante_inicial antes da primeira vigencia; a guarda cobre o caso
    # patologico. No modo aditivo o drawdown pode ser < -100%, e isso e o
    # resultado correto de um sistema de notional fixo que perdeu mais que
    # o capital inicial.
    max_acum = curva_investido.cummax()
    dd_series = ((curva_investido - max_acum) / max_acum.where(max_acum > 0))
    drawdown_max = float(dd_series.min()) if dd_series.notna().any() else np.nan

    vol_aa = float(ret_investido.std() * np.sqrt(252))
    ret_aa_simples = float(ret_investido.mean() * 252)
    sharpe = ret_aa_simples / vol_aa if vol_aa and vol_aa > 0 else np.nan

    # metricas de operacoes da estrategia WF
    ops_wf = metricas_operacoes_wf(ops_por_hilo, selecoes, idx)

    if not ops_wf.empty:
        total_ops_wf = int(len(ops_wf))
        pos_lucro_wf = int((ops_wf["pnl_operacao"] > 0).sum())
        taxa_acerto_wf = pos_lucro_wf / total_ops_wf
        ganho_medio_wf = ops_wf.loc[ops_wf["pnl_operacao"] > 0, "pnl_operacao"].mean()
        perda_media_wf = ops_wf.loc[ops_wf["pnl_operacao"] < 0, "pnl_operacao"].mean()
        payoff_wf = (
            ganho_medio_wf / abs(perda_media_wf)
            if pd.notna(ganho_medio_wf) and pd.notna(perda_media_wf) and perda_media_wf != 0
            else np.nan
        )
    else:
        total_ops_wf = 0
        taxa_acerto_wf = np.nan
        ganho_medio_wf = np.nan
        perda_media_wf = np.nan
        payoff_wf = np.nan

    esperanca_wf = (
        payoff_wf * taxa_acerto_wf - (1 - taxa_acerto_wf)
        if pd.notna(payoff_wf) and pd.notna(taxa_acerto_wf)
        else np.nan
    )
    expec_mat_wf = (
        ganho_medio_wf * taxa_acerto_wf - abs(perda_media_wf) * (1 - taxa_acerto_wf)
        if pd.notna(ganho_medio_wf) and pd.notna(perda_media_wf) and pd.notna(taxa_acerto_wf)
        else np.nan
    )

    resumo = {
        "Ativo": ticker,
        "Modo_Composicao": modo_composicao,
        "Qtd_Trocas_HiLo": int(len(selecoes)),
        "Qtd_Selecoes_Flat": int(len(flats)),
        "Qtd_Selecoes_Criterio": int(sum(1 for d in selecoes if d.get("origem") == "criterio")),
        "Qtd_Selecoes_Repetidas": int(sum(1 for d in selecoes if d.get("origem") == "repetido")),
        "Qtd_Selecoes_Fallback": int(sum(1 for d in selecoes if d.get("origem") == "fallback_inicial")),
        "Metrica_Estagio2": metrica_estagio2,
        "Qtd_Selecoes_Expec_Negativa": int(sum(
            1 for d in selecoes
            if d.get("origem") == "criterio" and np.isfinite(d.get("expec_escolhido", np.nan))
            and d["expec_escolhido"] <= 0)),
        "Qtd_HiLos_Distintos": int(trocas_df["HiLo_Escolhido"].nunique()),
        "HiLo_Ultimo_Selecionado": int(selecoes[-1]["hilo"]),
        "Perc_Tempo_Investido": float(mask_valid.mean()),
        "Rent_Total_WF": rent_total,
        "Rent_AA_WF": rent_aa,
        "Drawdown_WF": drawdown_max,
        "Vol_AA_WF": vol_aa,
        "Sharpe_WF": sharpe,
        "Total_Operacoes_WF": total_ops_wf,
        "Taxa_Acerto_WF": taxa_acerto_wf,
        "Ganho_Medio_WF": ganho_medio_wf,
        "Perda_Media_WF": perda_media_wf,
        "Payoff_WF": payoff_wf,
        "Esperanca_WF": esperanca_wf,
        "Expec_Mat_WF": expec_mat_wf,
        "Inicio_Amostra": idx[0],
        "Inicio_WF": data_inicio_wf,
        "Fim_WF": data_fim_wf,
        "Dias_Investidos_WF": int(n_investido),
    }

    # Operacoes FECHADAS da estrategia WF, lancadas na barra de fechamento.
    # Necessarias para reconstruir a esperanca acumulada do ativo em qualquer
    # data — insumo da camada de carteira (aba Carteira_WF). Sem isso, so o
    # numero final estaria disponivel, e ele carrega look-ahead.
    pnl_op_fech = pd.Series(0.0, index=idx)
    n_op_fech = pd.Series(0.0, index=idx)
    if not ops_wf.empty:
        agrup = ops_wf.groupby("data_fim")["pnl_operacao"]
        soma = agrup.sum()
        cont = agrup.size()
        pnl_op_fech.loc[pnl_op_fech.index.intersection(soma.index)] = soma.reindex(
            pnl_op_fech.index.intersection(soma.index)).values
        n_op_fech.loc[n_op_fech.index.intersection(cont.index)] = cont.reindex(
            n_op_fech.index.intersection(cont.index)).values

        # separa ganhos e perdas para reconstruir payoff e taxa de acerto
        ganhos = ops_wf[ops_wf["pnl_operacao"] > 0].groupby("data_fim")["pnl_operacao"]
        perdas = ops_wf[ops_wf["pnl_operacao"] < 0].groupby("data_fim")["pnl_operacao"]
    else:
        ganhos = perdas = None

    def _serie(gr, como):
        out = pd.Series(0.0, index=idx)
        if gr is None:
            return out
        v = gr.sum() if como == "soma" else gr.size()
        inter = out.index.intersection(v.index)
        if len(inter):
            out.loc[inter] = v.reindex(inter).values
        return out

    curva_df = pd.DataFrame({
        "Ativo": ticker,
        "Data": idx,
        "HiLo_Vigente": hilo_vigente.values,
        "Pnl_Diario_WF": pnl_estrategia.values,
        "Ret_Diario_WF": ret_estrategia.values,
        "Curva_WF": curva.values,
        "Ops_Fechadas": n_op_fech.values,
        "Pnl_Ops_Fechadas": pnl_op_fech.values,
        "Ops_Ganho": _serie(ganhos, "cont").values,
        "Pnl_Ganhos": _serie(ganhos, "soma").values,
        "Ops_Perda": _serie(perdas, "cont").values,
        "Pnl_Perdas": _serie(perdas, "soma").values,
    })

    return resumo, trocas_df, curva_df

# =========================
# EXECUCAO (SOMENTE WALK-FORWARD)
# =========================
# =========================
# METRICAS DE TODOS OS HILOS (diagnostico)
# =========================
def montar_metricas_por_hilo(ticker, ops_por_hilo):
    """
    Esperanca matematica e metricas de operacao de CADA hilo testado, sobre a
    amostra inteira. Uma linha por (ativo, hilo).

    ATENCAO — ISTO E DIAGNOSTICO, NAO CRITERIO. As metricas aqui usam o
    periodo COMPLETO, entao escolher um hilo olhando esta aba e look-ahead:
    o numero so existe depois que tudo aconteceu. Serve para ver o formato da
    superficie (a esperanca varia suave ou e ruido? o payoff so cresce com o
    comprimento?) e para conferir o que a selecao walk-forward escolheu contra
    o que teria sido o melhor em retrospecto.

    Duracao_Media_Ganhos / _Perdas: numero medio de pregoes que a operacao
    ficou aberta. E a assinatura do seguidor de tendencia — deixar o ganho
    correr e cortar a perda cedo aparece aqui como razao bem acima de 1.

    Blocos _Long e _Short: as mesmas metricas restritas a operacoes compradas
    e vendidas. Importa separar porque o custo real difere (venda a descoberto
    paga aluguel na B3, compra nao) e porque acao brasileira tem tendencia de
    alta de longo prazo — se o resultado vier todo do lado comprado, a
    estrategia e beta disfarcado, nao captura de tendencia.

    Payoff_Ajustado: residuo padronizado da regressao payoff ~ log(hilo)
    dentro do ativo — quanto o hilo entrega de payoff acima do esperado para
    uma janela daquele tamanho. Mesma definicao usada em METRICA_HILO =
    "payoff_ajustado", aqui aplicada a amostra toda.
    """
    linhas = []
    for hilo, g in sorted(ops_por_hilo.items()):
        if g is None or g.empty or "trade_id" not in g.columns:
            continue
        gv = g.dropna(subset=["trade_id"])
        if gv.empty:
            continue

        # por operacao: pnl total, direcao (+1 comprado, -1 vendido) e
        # DURACAO em barras (numero de pregoes que o trade ficou aberto)
        agg = gv.groupby("trade_id").agg(
            pnl=("pnl", "sum"),
            direcao=("trade_decision", "first"),
            duracao=("pnl", "size"),
        )
        trades = agg["pnl"].values
        n = len(trades)
        if n == 0:
            continue

        dur = agg["duracao"].values
        dirc = agg["direcao"].values
        dur_g = float(dur[trades > 0].mean()) if (trades > 0).any() else np.nan
        dur_p = float(dur[trades < 0].mean()) if (trades < 0).any() else np.nan

        def _bloco(mask, sufixo):
            """Metricas restritas a um subconjunto de operacoes."""
            t = trades[mask]
            if len(t) == 0:
                return {f"Ops_{sufixo}": 0}
            w, l = t[t > 0], t[t < 0]
            gm = float(w.mean()) if len(w) else np.nan
            pm = abs(float(l.mean())) if len(l) else np.nan
            dd = dur[mask]
            return {
                f"Ops_{sufixo}": int(len(t)),
                f"Taxa_Acerto_{sufixo}": float(len(w) / len(t) * 100),
                f"Expec_Mat_{sufixo}": float(t.mean()),
                f"Payoff_{sufixo}": (gm / pm if (pm and pm > 0) else np.nan),
                f"Profit_Factor_{sufixo}": (float(w.sum() / abs(l.sum()))
                                            if len(l) and l.sum() != 0 else np.nan),
                f"Resultado_{sufixo}": float(t.sum()),
                f"Duracao_Media_Ganhos_{sufixo}": (float(dd[t > 0].mean())
                                                   if (t > 0).any() else np.nan),
                f"Duracao_Media_Perdas_{sufixo}": (float(dd[t < 0].mean())
                                                   if (t < 0).any() else np.nan),
            }

        bloco_long = _bloco(dirc > 0, "Long")
        bloco_short = _bloco(dirc < 0, "Short")

        win = trades[trades > 0]
        los = trades[trades < 0]
        nw, nl = len(win), len(los)
        sg, sl = float(win.sum()), float(los.sum())

        p_acerto = nw / n
        ganho_m = sg / nw if nw else np.nan
        perda_m = abs(sl / nl) if nl else np.nan
        payoff = ganho_m / perda_m if (perda_m and perda_m > 0) else np.nan
        pf = sg / abs(sl) if sl != 0 else np.nan
        expec = (sg + sl) / n
        esper_r = payoff * p_acerto - (1.0 - p_acerto) if np.isfinite(payoff) else np.nan

        # t/p do retorno diario do hilo (mesma base do 1o estagio da selecao)
        r_d = (g["pnl"] / float(montante_inicial)).values
        r_d = r_d[np.isfinite(r_d)]
        nz = np.flatnonzero(r_d != 0.0)
        if len(nz):
            r_d = r_d[nz[0]:]
        sd = float(np.std(r_d, ddof=1)) if len(r_d) > 2 else 0.0
        t_val = (float(np.mean(r_d)) / (sd / np.sqrt(len(r_d)))) if sd > 0 else np.nan

        linhas.append({
            "Ativo": ticker,
            "HiLo": int(hilo),
            "Total_Operacoes": n,
            "Ops_Ganho": nw,
            "Ops_Perda": nl,
            "Taxa_Acerto": p_acerto * 100.0,
            "Ganho_Medio": ganho_m,
            "Perda_Media": -perda_m if np.isfinite(perda_m) else np.nan,
            "Payoff": payoff,
            "Profit_Factor": pf,
            "Expec_Mat": expec,
            "Esperanca_R": esper_r,
            "Resultado_Total": sg + sl,
            "Duracao_Media_Ganhos": dur_g,
            "Duracao_Media_Perdas": dur_p,
            "Razao_Duracao_Ganho_Perda": (dur_g / dur_p
                                          if (dur_p and dur_p > 0) else np.nan),
            **bloco_long,
            **bloco_short,
            "N_Barras": len(r_d),
            "t_Padrao": t_val,
            "p_Unilateral": (float(1.0 - stats.norm.cdf(t_val))
                             if np.isfinite(t_val) else np.nan),
        })

    if not linhas:
        return pd.DataFrame()

    df = pd.DataFrame(linhas)

    # payoff ajustado pelo comprimento, dentro deste ativo
    ok = df["Payoff"].notna() & (df["HiLo"] > 0)
    df["Payoff_Ajustado"] = np.nan
    if int(ok.sum()) >= minimo_hilos_ajuste:
        x = np.log(df.loc[ok, "HiLo"].values.astype(float))
        y = df.loc[ok, "Payoff"].values
        b1, b0 = np.polyfit(x, y, 1)
        resid = df["Payoff"].values - (b0 + b1 * np.log(df["HiLo"].values.astype(float)))
        sd_r = float(np.nanstd(resid[ok.values]))
        df["Payoff_Ajustado"] = resid / sd_r if sd_r > 0 else resid
        df["Inclinacao_Payoff_vs_logHilo"] = float(b1)

    return df



def _sem_suspeitos(df, coluna="Ativo"):
    """Remove ativos marcados como suspeitos das analises AGREGADAS."""
    if not excluir_suspeitos_agregados or not ativos_suspeitos or df is None or df.empty:
        return df
    return df[~df[coluna].isin(ativos_suspeitos)]


def montar_agregado_por_hilo(hilos_metricas_df):
    """
    Agrega as metricas de TODOS os ativos para CADA hilo — uma linha por hilo.

    Responde: o valor do hilo importa para a CARTEIRA, ou so redistribui
    resultado entre ativos? Se houvesse compensacao perfeita (um ativo melhora
    quando outro piora), o agregado seria plano e a escolha do hilo seria
    irrelevante no nivel do portfolio.

    Colunas-chave:
      Resultado_Agregado  soma do resultado de todos os ativos naquele hilo.
                          E a linha do portfolio: se for plana, o hilo nao
                          muda o total.
      Expec_Carteira      resultado agregado / operacoes agregadas. Esperanca
                          por operacao no nivel da carteira (ponderada por
                          numero de trades, nao media simples entre ativos).
      Expec_Mat_Mediana   mediana entre ativos. Preferir a media: a media e
                          dominada por poucos ativos com resultado extremo.
      DP_Entre_Ativos     dispersao entre ativos dentro do mesmo hilo. Se for
                          muito maior que a variacao do agregado entre hilos,
                          entao QUAL ATIVO importa muito mais que QUAL HILO.
      Rho_vs_Hilo_Anterior  correlacao de Spearman do ranking dos ativos entre
                          este hilo e o anterior. Perto de 1 = os mesmos
                          ativos vao bem em qualquer hilo, ou seja, NAO ha
                          compensacao; perto de 0 ou negativo = ha.
    """
    if hilos_metricas_df is None or hilos_metricas_df.empty:
        return pd.DataFrame()

    d = _sem_suspeitos(hilos_metricas_df)
    if d.empty:
        return pd.DataFrame()
    linhas = []
    piv = d.pivot_table(index="Ativo", columns="HiLo", values="Expec_Mat")
    hilos = sorted(d["HiLo"].unique())

    for i, h in enumerate(hilos):
        x = d[d["HiLo"] == h]
        ops = float(x["Total_Operacoes"].sum())
        res = float(x["Resultado_Total"].sum())

        rho = np.nan
        if i > 0 and h in piv.columns and hilos[i - 1] in piv.columns:
            par = piv[[hilos[i - 1], h]].dropna()
            if len(par) >= 5:
                rho = float(stats.spearmanr(par.iloc[:, 0], par.iloc[:, 1]).statistic)

        linhas.append({
            "HiLo": int(h),
            "N_Ativos": int(len(x)),
            "Resultado_Agregado": res,
            "Operacoes_Agregadas": int(ops),
            "Expec_Carteira": res / ops if ops > 0 else np.nan,
            "Expec_Mat_Mediana": float(x["Expec_Mat"].median()),
            "Expec_Mat_Media": float(x["Expec_Mat"].mean()),
            "DP_Entre_Ativos": float(x["Expec_Mat"].std()),
            "Perc_Ativos_Expec_Positiva": float((x["Expec_Mat"] > 0).mean() * 100),
            "Payoff_Mediano": float(x["Payoff"].median()),
            "Taxa_Acerto_Mediana": float(x["Taxa_Acerto"].median()),
            "Ops_Medias_Por_Ativo": float(x["Total_Operacoes"].mean()),
            "Rho_vs_Hilo_Anterior": rho,
        })

    ag = pd.DataFrame(linhas)

    # diagnostico final: o agregado varia mais entre HILOS ou entre ATIVOS?
    if len(ag) > 2:
        var_hilos = ag["Expec_Mat_Media"].std()
        var_ativos = ag["DP_Entre_Ativos"].mean()
        ag.attrs["razao_hilo_ativo"] = (var_hilos / var_ativos
                                        if var_ativos > 0 else np.nan)
    return ag



def montar_carteiras_aleatorias(hilos_metricas_df):
    """
    Teste de estabilidade: sorteia carteiras aleatorias de N ativos e mede o
    resultado de cada HILO FIXO, liquido de custo de transacao.

    Responde duas perguntas que o agregado unico nao responde:
      (a) o resultado depende de quais ativos entraram? -> dispersao entre
          sorteios (P10 a P90) com o hilo de referencia fixo;
      (b) escolher o hilo importa mais ou menos que escolher os ativos? ->
          razao entre a amplitude ao variar o hilo e a amplitude ao variar
          o sorteio.

    ATENCAO AO QUE ISTO E E AO QUE NAO E: os sorteios se sobrepoem (N de um
    universo pequeno), cobrem o mesmo periodo e o mesmo mercado. E teste de
    ESTABILIDADE — mostra que o resultado nao depende de quais ativos foram
    pegos. NAO sao observacoes independentes e NAO constituem teste de
    significancia; o p-valor continua sendo o da aba "p valor".

    O custo entra como bps sobre o notional por operacao: cada operacao
    encerrada perde custo_bps/10000 * montante_inicial. E o que separa hilos
    curtos (muito giro) de longos (pouco giro) — no bruto eles empatam.

    Retorna (df_curva, df_resumo).
    """
    if hilos_metricas_df is None or hilos_metricas_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    hilos_metricas_df = _sem_suspeitos(hilos_metricas_df)
    if hilos_metricas_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    res = hilos_metricas_df.pivot_table(index="Ativo", columns="HiLo",
                                        values="Resultado_Total").dropna()
    if res.empty or res.shape[0] < 5:
        return pd.DataFrame(), pd.DataFrame()
    ops = (hilos_metricas_df.pivot_table(index="Ativo", columns="HiLo",
                                         values="Total_Operacoes")
           .reindex(index=res.index, columns=res.columns).fillna(0.0))

    hilos = np.array([int(h) for h in res.columns])
    Rv, Ov = res.values, ops.values
    n_ativos = len(res)
    rng = np.random.default_rng(semente_simulacao)

    curva, resumo = [], []
    for K in tamanhos_carteira_simulacao:
        if K > n_ativos:
            continue
        idx = np.array([rng.choice(n_ativos, K, replace=False)
                        for _ in range(n_simulacoes_carteira)])
        bruto = Rv[idx].sum(axis=1)          # (n_sim, n_hilos)
        n_ops = Ov[idx].sum(axis=1)

        for custo in custos_bps_simulacao:
            # custo por operacao em R$ sobre o notional fixo
            liq = (bruto - n_ops * (custo / 10000.0) * montante_inicial) / K
            arg = hilos[liq.argmax(axis=1)]
            otimo_por_hilo = np.array([(arg == h).mean() for h in hilos])

            for k, h in enumerate(hilos):
                curva.append({
                    "Tamanho_Carteira": K,
                    "Custo_bps": custo,
                    "HiLo": int(h),
                    "N_Simulacoes": int(n_simulacoes_carteira),
                    "Resultado_Mediano_Por_Ativo": float(np.median(liq[:, k])),
                    "P10_Por_Ativo": float(np.percentile(liq[:, k], 10)),
                    "P90_Por_Ativo": float(np.percentile(liq[:, k], 90)),
                    "Perc_Carteiras_Positivas": float((liq[:, k] > 0).mean() * 100),
                    "Perc_Vezes_Este_Hilo_Foi_Otimo": float(otimo_por_hilo[k] * 100),
                })

            jr = int(np.flatnonzero(hilos == hilo_referencia_simulacao)[0]) \
                if (hilos == hilo_referencia_simulacao).any() else int(np.argmax(np.median(liq, axis=0)))
            jc = int(np.flatnonzero(hilos == hilo_comparacao_simulacao)[0]) \
                if (hilos == hilo_comparacao_simulacao).any() else 0

            med = np.median(liq, axis=0)
            disp_sorteio = float(np.percentile(liq[:, jr], 90) - np.percentile(liq[:, jr], 10))
            disp_hilo = float(med.max() - med.min())
            with np.errstate(invalid="ignore", divide="ignore"):
                ganho = liq[:, jr] / np.where(liq[:, jc] != 0, liq[:, jc], np.nan) - 1.0

            resumo.append({
                "Tamanho_Carteira": K,
                "Custo_bps": custo,
                "N_Simulacoes": int(n_simulacoes_carteira),
                "HiLo_Referencia": int(hilos[jr]),
                "HiLo_Comparacao": int(hilos[jc]),
                "Result_Mediano_Referencia": float(med[jr]),
                "P10_Referencia": float(np.percentile(liq[:, jr], 10)),
                "P90_Referencia": float(np.percentile(liq[:, jr], 90)),
                "Perc_Carteiras_Positivas_Ref": float((liq[:, jr] > 0).mean() * 100),
                "Perc_Referencia_Vence_Comparacao": float((liq[:, jr] > liq[:, jc]).mean() * 100),
                "Ganho_Mediano_vs_Comparacao_Perc": float(np.nanmedian(ganho) * 100),
                "HiLo_Otimo_Mediano": float(np.median(arg)),
                "HiLo_Otimo_P10": float(np.percentile(arg, 10)),
                "HiLo_Otimo_P90": float(np.percentile(arg, 90)),
                "Perc_Otimo_Entre_65_e_100": float(((arg >= 65) & (arg <= 100)).mean() * 100),
                "Perc_Otimo_Abaixo_de_20": float((arg < 20).mean() * 100),
                "Amplitude_Por_Sorteio": disp_sorteio,
                "Amplitude_Por_Hilo": disp_hilo,
                "Razao_Hilo_Sobre_Sorteio": (disp_hilo / disp_sorteio
                                             if disp_sorteio > 0 else np.nan),
            })

    return pd.DataFrame(curva), pd.DataFrame(resumo)



def montar_janelas_hilo_fixo(ret_liq_por_hilo):
    """
    Percentual de janelas moveis positivas de carteiras aleatorias operando um
    HILO FIXO — sem walk-forward, sem selecao de ativo, sem selecao de hilo.

    Para cada hilo em "hilos_fixos_janelas" e cada tamanho em
    "tamanhos_janelas", sorteia "n_simulacoes_janelas" carteiras equal-weight
    e mede, na curva de capital de cada uma, a fracao de janelas moveis de
    "janelas_carteira" pregoes que terminam positivas.

    O custo entra descontado do pnl na barra de FECHAMENTO de cada operacao,
    a "custo_bps_janelas" bps do notional — e o que separa hilo curto de longo.

    ATENCAO: janelas moveis sao SOBREPOSTAS. Uma serie de 5.000 barras produz
    ~4.750 janelas de 250 dias, mas so ~20 independentes. O percentual e
    informativo sobre a experiencia de quem carrega a posicao; NAO e tamanho
    amostral. A coluna Janelas_Independentes registra a ordem de grandeza.

    ret_liq_por_hilo: {hilo: DataFrame(index=Data, columns=Ativo)} com o
    retorno diario JA LIQUIDO de custo (pnl / montante_inicial).
    """
    if not ret_liq_por_hilo:
        return pd.DataFrame()

    rng = np.random.default_rng(semente_simulacao)
    linhas = []

    for hilo in sorted(ret_liq_por_hilo):
        R = ret_liq_por_hilo[hilo].sort_index()
        if excluir_suspeitos_agregados and ativos_suspeitos:
            R = R[[c for c in R.columns if c not in ativos_suspeitos]]
        if R.empty or R.shape[1] < 3:
            continue
        vivos = R.notna()
        Rv = R.fillna(0.0).values
        Vv = vivos.values.astype(float)
        n_ativos = R.shape[1]

        for K in tamanhos_janelas:
            if K > n_ativos:
                continue
            perc = {w: [] for w in janelas_carteira}
            geo = []
            descartadas = 0
            for _ in range(n_simulacoes_janelas):
                sel = rng.choice(n_ativos, K, replace=False)
                soma = Vv[:, sel].sum(axis=1)
                # equal-weight entre os ativos VIVOS em cada barra
                r = np.where(soma > 0, Rv[:, sel].sum(axis=1) / np.where(soma > 0, soma, 1.0), 0.0)
                curva = np.cumprod(1.0 + r)
                n = len(curva)
                if n < max(janelas_carteira) + 10:
                    continue
                # GUARDA: curva nao positiva significa que alguma barra teve
                # retorno <= -100%. Nao existe estrategia assim — e dado sujo.
                # Antes, isso gerava NaN silencioso em curva[-1]**(252/n) e o
                # np.median contaminava TODAS as linhas da aba.
                if not np.all(np.isfinite(curva)) or np.any(curva <= 0):
                    descartadas += 1
                    continue
                geo.append(curva[-1] ** (252.0 / n) - 1.0)
                for w in janelas_carteira:
                    rr = curva[w:] / curva[:-w] - 1.0
                    perc[w].append(float((rr > 0).mean() * 100.0))

            if not geo:
                continue
            if descartadas:
                print(f"  AVISO janelas hilo {hilo}, carteira de {K}: "
                      f"{descartadas} de {n_simulacoes_janelas} simulacoes descartadas "
                      f"(curva de capital nao positiva — dado sujo).")
            n_barras = R.shape[0]
            for w in janelas_carteira:
                v = np.array(perc[w])
                linhas.append({
                    "HiLo_Fixo": int(hilo),
                    "Tamanho_Carteira": K,
                    "Custo_bps": custo_bps_janelas,
                    "Janela_Dias": w,
                    "N_Simulacoes": len(v),
                    "N_Simulacoes_Descartadas": int(descartadas),
                    "Perc_Janelas_Positivas_Mediana": float(np.nanmedian(v)),
                    "Perc_Positivas_P10": float(np.nanpercentile(v, 10)),
                    "Perc_Positivas_P90": float(np.nanpercentile(v, 90)),
                    "Janelas_Sobrepostas": int(n_barras - w),
                    "Janelas_Independentes": int(n_barras / w),
                    "Rent_AA_Geometrica_Mediana": float(np.nanmedian(geo) * 100.0),
                })
    return pd.DataFrame(linhas)




def _teste_pareado(ra, rb, rot_a, rot_b, hilo, n_boot):
    """
    Teste pareado sobre a serie DIARIA da diferenca entre duas estrategias.

    Comparar dois p-valores isolados e fraco: as duas carteiras compartilham
    o mesmo fator de mercado, e a maior parte da variancia e comum. Testar a
    serie da diferenca elimina esse fator e da muito mais poder.

    H0: retorno medio de A = retorno medio de B.
    """
    dif = np.asarray(ra, float) - np.asarray(rb, float)
    dif = dif[np.isfinite(dif)]
    n = len(dif)
    if n < 100 or np.std(dif, ddof=1) == 0:
        return None
    sd = float(np.std(dif, ddof=1))
    t = float(np.mean(dif) / (sd / np.sqrt(n)))
    t_nw, p_nw, lags = _t_newey_west(dif)
    return {
        "HiLo_Fixo": int(hilo),
        "Comparacao": f"{rot_a} - {rot_b}",
        "Tipo": "Diferenca diaria (pareado)",
        "N_Barras": n,
        "Dif_Media_AA_pp": float(np.mean(dif) * 252 * 100),
        "Vol_Dif_AA": sd * np.sqrt(252) * 100,
        "t_Padrao": t,
        "p_Padrao": float(2 * (1 - stats.norm.cdf(abs(t)))),
        "t_NeweyWest": t_nw, "p_NeweyWest": p_nw, "NW_Lags": lags,
        "p_Bootstrap_Bloco": _p_bootstrap_bloco(dif, n_boot=n_boot),
    }


def _teste_janelas_pareado(ca, cb, rot_a, rot_b, hilo, w):
    """
    McNemar sobre janelas INDEPENDENTES (nao sobrepostas).

    Responde diretamente "87,8% contra 77,9% e diferenca real ou sao 3 anos
    em 26?". Compara, janela a janela, se A foi positiva e B negativa (b) ou
    o contrario (c). So os pares DISCORDANTES carregam informacao; o teste e
    binomial exato sobre b de (b+c).
    """
    ca, cb = np.asarray(ca, float), np.asarray(cb, float)
    n = len(ca)
    if n <= w:
        return None
    corte = np.arange(0, n, w)            # janelas nao sobrepostas
    if len(corte) < 3:
        return None
    ra = ca[corte[1:]] / ca[corte[:-1]] - 1.0
    rb = cb[corte[1:]] / cb[corte[:-1]] - 1.0
    pa, pb = ra > 0, rb > 0
    b = int(np.sum(pa & ~pb))             # A positiva, B negativa
    c = int(np.sum(~pa & pb))             # A negativa, B positiva
    disc = b + c
    p = float(stats.binomtest(b, disc, 0.5).pvalue) if disc > 0 else np.nan
    return {
        "HiLo_Fixo": int(hilo),
        "Comparacao": f"{rot_a} - {rot_b}",
        "Tipo": f"McNemar janelas {w}d independentes",
        "N_Barras": int(len(corte) - 1),
        "Perc_Positivas_A": float(pa.mean() * 100),
        "Perc_Positivas_B": float(pb.mean() * 100),
        "So_A_Positiva": b, "So_B_Positiva": c, "Discordantes": disc,
        "p_Padrao": p,
    }


def _metricas_serie(ret, curva, frac_investido, rot_ativo, rot_estrat, hilo):
    """Metricas completas de uma serie diaria + janelas moveis positivas."""
    n = len(ret)
    if n < 100:
        return None
    sd = float(np.std(ret, ddof=1))
    rent_total = float(curva[-1] / montante_inicial - 1.0)
    linha = {
        "Ativo": rot_ativo,
        "HiLo_Fixo": int(hilo),
        "Estrategia": rot_estrat,
        "N_Barras": n,
        "Anos": n / 252.0,
        "Perc_Tempo_Investido": float(frac_investido * 100),
        "Rent_Total": rent_total * 100,
        "Rent_AA_Geometrica": (float(curva[-1] / montante_inicial) ** (252.0 / n) - 1.0) * 100
                              if curva[-1] > 0 else np.nan,
        "Vol_AA": sd * np.sqrt(252) * 100,
        "Sharpe_rf0": float(np.mean(ret) / sd * np.sqrt(252)) if sd > 0 else np.nan,
        "Drawdown_Max": float((curva / np.maximum.accumulate(curva) - 1.0).min() * 100),
    }
    for w in janelas_carteira:
        if n > w:
            rr = curva[w:] / curva[:-w] - 1.0
            linha[f"Perc_Janelas_{w}d_Positivas"] = float((rr > 0).mean() * 100)
    return linha


def montar_longonly_vs_bh(series_por_hilo):
    """
    Compara, com CURVA DIARIA, quatro alternativas para cada hilo fixo:

      LongShort   posicao comprada e vendida (HiLo classico)
      LongOnly    so a perna comprada; fica em CAIXA no lugar do short
      LongOnly+CDI  idem, com o caixa ocioso rendendo cdi_aa_longonly
      BuyAndHold  comprado 100% do tempo, sem sinal

    Sai uma linha por (ativo, hilo, estrategia) e uma linha de CARTEIRA
    equal-weight. Metricas: retorno total e geometrico, vol, Sharpe,
    drawdown, tempo investido e % de janelas moveis positivas.

    POR QUE O CDI IMPORTA AQUI: o long-only fica fora do mercado ~45% do
    tempo. Ignorar o rendimento do caixa subestima a estrategia em varios
    pontos ao ano — e essa e a comparacao honesta contra buy-and-hold, que
    usa 100% do capital o tempo todo.

    O custo de transacao ja vem descontado nas series de entrada.
    """
    if not series_por_hilo:
        return pd.DataFrame()

    linhas, diario, testes = [], [], []
    cdi_diario = (1.0 + cdi_aa_longonly / 100.0) ** (1.0 / 252.0) - 1.0

    for hilo in sorted(series_por_hilo):
        d = series_por_hilo[hilo]
        if not d:
            continue
        rl = pd.DataFrame({a: v["long_short"] for a, v in d.items()}).sort_index()
        ro = pd.DataFrame({a: v["long_only"] for a, v in d.items()}).reindex_like(rl)
        rb = pd.DataFrame({a: v["buy_hold"] for a, v in d.items()}).reindex_like(rl)
        inv = pd.DataFrame({a: v["investido"] for a, v in d.items()}).reindex_like(rl)

        if excluir_suspeitos_agregados and ativos_suspeitos:
            manter = [c for c in rl.columns if c not in ativos_suspeitos]
            rl, ro, rb, inv = rl[manter], ro[manter], rb[manter], inv[manter]
        if rl.empty:
            continue

        def _emitir(serie_ret, serie_inv, ativo, estrat):
            r = np.asarray(serie_ret, dtype=float)
            r = np.nan_to_num(r, nan=0.0)
            if estrat == "LongOnly+CDI":
                r = r + (1.0 - np.asarray(serie_inv, dtype=float)) * cdi_diario
            if np.any(1.0 + r <= 0):
                return None
            curva = montante_inicial * np.cumprod(1.0 + r)
            return _metricas_serie(r, curva, float(np.nanmean(serie_inv)),
                                   ativo, estrat, hilo)

        # por ativo
        for a in rl.columns:
            iv = inv[a].fillna(0.0).values
            for serie, estrat in [(rl[a], "LongShort"), (ro[a], "LongOnly"),
                                  (ro[a], "LongOnly+CDI"), (rb[a], "BuyAndHold")]:
                ivv = np.ones_like(iv) if estrat == "BuyAndHold" else iv
                li = _emitir(serie.values, ivv, a, estrat)
                if li:
                    linhas.append(li)

        # carteira equal-weight entre os ativos vivos em cada barra
        vivos = rl.notna().sum(axis=1).replace(0, np.nan)
        inv_c = (inv.fillna(0.0).sum(axis=1) / vivos).fillna(0.0).values
        series_cart, curvas_cart = {}, {}
        for frame, estrat in [(rl, "LongShort"), (ro, "LongOnly"),
                              (ro, "LongOnly+CDI"), (rb, "BuyAndHold")]:
            serie = (frame.fillna(0.0).sum(axis=1) / vivos).fillna(0.0).values
            ivv = np.ones_like(inv_c) if estrat == "BuyAndHold" else inv_c
            li = _emitir(serie, ivv, "CARTEIRA_EQUAL_WEIGHT", estrat)
            if li:
                linhas.append(li)
            r = np.nan_to_num(np.asarray(serie, float), nan=0.0)
            if estrat == "LongOnly+CDI":
                r = r + (1.0 - np.asarray(ivv, float)) * cdi_diario
            series_cart[estrat] = r
            curvas_cart[estrat] = montante_inicial * np.cumprod(1.0 + r)

        bloco = {"Data": rl.index, "HiLo_Fixo": int(hilo),
                 "Frac_Investido": inv_c}
        for e, r in series_cart.items():
            bloco[f"Ret_{e}"] = r
            bloco[f"Curva_{e}"] = curvas_cart[e]
        diario.append(pd.DataFrame(bloco))

        # ---- testes pareados ----
        pares = [("LongOnly+CDI", "BuyAndHold"), ("LongOnly", "BuyAndHold"),
                 ("LongOnly", "LongShort"), ("LongOnly+CDI", "LongShort")]
        for A, B in pares:
            t = _teste_pareado(series_cart[A], series_cart[B], A, B,
                               hilo, n_boot_pvalor)
            if t:
                testes.append(t)
            for w in janelas_carteira:
                tj = _teste_janelas_pareado(curvas_cart[A], curvas_cart[B],
                                            A, B, hilo, w)
                if tj:
                    testes.append(tj)

    return (pd.DataFrame(linhas),
            pd.concat(diario, ignore_index=True) if diario else pd.DataFrame(),
            pd.DataFrame(testes))


def _maior_sequencia(mask_bool, idx):
    """Maior sequencia contigua de True. Retorna (tamanho, data_ini, data_fim)."""
    v = np.asarray(mask_bool, dtype=bool)
    if not v.any():
        return 0, pd.NaT, pd.NaT
    quebras = np.flatnonzero(np.diff(np.concatenate(([0], v.view(np.int8), [0]))))
    ini, fim = quebras[0::2], quebras[1::2]
    k = int(np.argmax(fim - ini))
    return int(fim[k] - ini[k]), idx[ini[k]], idx[fim[k] - 1]



def montar_longonly_subamostras(series_por_hilo):
    """
    Metricas das quatro estrategias em CARTEIRAS ALEATORIAS de N ativos.

    A linha CARTEIRA_EQUAL_WEIGHT de LongOnly_vs_BH usa o universo INTEIRO,
    entao nao diz nada sobre dependencia da escolha de ativos. Aqui sorteia-se
    "n_simulacoes_longonly" carteiras de cada tamanho em
    "tamanhos_carteira_longonly" e reporta-se mediana, P10 e P90 de cada
    metrica.

    O QUE ISTO RESOLVE E O QUE NAO RESOLVE: responde "o resultado depende de
    quais ativos eu peguei?". NAO melhora significancia — os sorteios
    compartilham o mesmo periodo e as mesmas janelas independentes, entao o
    numero de observacoes no tempo continua o mesmo. Para o teste pareado,
    veja a aba LongOnly_Testes.
    """
    if not series_por_hilo:
        return pd.DataFrame()

    cdi_diario = (1.0 + cdi_aa_longonly / 100.0) ** (1.0 / 252.0) - 1.0
    linhas = []

    # semente REINICIADA por (hilo, tamanho): os mesmos sorteios de ativos sao
    # usados em todos os hilos e nas quatro estrategias. Sem isso, comparar
    # hilos seria comparar carteiras diferentes — e BuyAndHold, que nao depende
    # do hilo, apareceria com valores distintos entre eles.
    for hilo in sorted(series_por_hilo):
        d = series_por_hilo[hilo]
        if not d:
            continue
        cols = [a for a in d
                if not (excluir_suspeitos_agregados and a in ativos_suspeitos)]
        if len(cols) < 5:
            continue
        # ALINHAR PELO INDICE, nao empilhar arrays: ativos tem historicos de
        # tamanhos diferentes (IPO em datas distintas), entao np.column_stack
        # quebra. O reindex pela UNIAO das datas preenche com NaN onde o ativo
        # ainda nao existe, e a mascara "vivo" garante que ele so entre na
        # media a partir da sua primeira barra.
        base = pd.DataFrame({a: d[a]["long_short"] for a in cols}).sort_index()
        idx = base.index
        M = {}
        for k in ("long_short", "long_only", "buy_hold", "investido"):
            F = pd.DataFrame({a: d[a][k] for a in cols}).reindex(index=idx, columns=cols)
            M[k] = F.fillna(0.0).values
        vivo = base.notna().values.astype(float)
        n_at = len(cols)

        for K in tamanhos_carteira_longonly:
            if K > n_at:
                continue
            rng = np.random.default_rng(semente_simulacao + K)
            sel = np.array([rng.choice(n_at, K, replace=False)
                            for _ in range(n_simulacoes_longonly)])
            nv = np.stack([vivo[:, s].sum(axis=1) for s in sel])          # (sim, barras)
            den = np.where(nv > 0, nv, 1.0)
            inv = np.stack([M["investido"][:, s].sum(axis=1) for s in sel]) / den

            for estrat, chave in [("LongShort", "long_short"), ("LongOnly", "long_only"),
                                  ("LongOnly+CDI", "long_only"), ("BuyAndHold", "buy_hold")]:
                R = np.stack([M[chave][:, s].sum(axis=1) for s in sel]) / den
                if estrat == "LongOnly+CDI":
                    R = R + (1.0 - inv) * cdi_diario
                ok = np.all(1.0 + R > 0, axis=1)
                if not ok.any():
                    continue
                R = R[ok]
                curva = np.cumprod(1.0 + R, axis=1)
                n = R.shape[1]
                geo = curva[:, -1] ** (252.0 / n) - 1.0
                vol = R.std(axis=1, ddof=1) * np.sqrt(252)
                dd = (curva / np.maximum.accumulate(curva, axis=1) - 1.0).min(axis=1)
                frac = np.ones(len(R)) if estrat == "BuyAndHold" else inv[ok].mean(axis=1)
                lin = {
                    "HiLo_Fixo": int(hilo), "Tamanho_Carteira": K, "Estrategia": estrat,
                    "N_Simulacoes": int(len(R)), "N_Descartadas": int((~ok).sum()),
                    "Perc_Tempo_Investido": float(np.median(frac) * 100),
                    "Rent_AA_Mediana": float(np.median(geo) * 100),
                    "Rent_AA_P10": float(np.percentile(geo, 10) * 100),
                    "Rent_AA_P90": float(np.percentile(geo, 90) * 100),
                    "Vol_AA_Mediana": float(np.median(vol) * 100),
                    "Drawdown_Mediano": float(np.median(dd) * 100),
                    "Drawdown_P10_pior": float(np.percentile(dd, 10) * 100),
                    "Sharpe_liq_CDI_Mediano": float(np.median(
                        (geo * 100 - cdi_aa_longonly) / (vol * 100))),
                    "Perc_Carteiras_Positivas": float((geo > 0).mean() * 100),
                }
                for w in janelas_carteira:
                    if n > w:
                        rr = curva[:, w:] / curva[:, :-w] - 1.0
                        lin[f"Perc_Janelas_{w}d_Mediana"] = float(
                            np.median((rr > 0).mean(axis=1)) * 100)
                linhas.append(lin)
    return pd.DataFrame(linhas)


def montar_lacunas_long(series_por_hilo):
    """
    Procura JANELAS LONGAS SEM POSICAO COMPRADA — por ativo e na carteira.

    Duas perguntas praticas:
      (a) por ATIVO: qual a maior sequencia de pregoes em que o HiLo nunca
          esteve comprado? Uma lacuna de anos significa capital parado sem
          que o sinal jamais autorizasse entrada.
      (b) na CARTEIRA: houve periodo em que quase NENHUM ativo estava
          comprado ao mesmo tempo? Isso e risco de concentracao temporal —
          a diversificacao entre 50 ativos nao ajuda se todos saem juntos.

    "limiar_exposicao_lacuna" define o que conta como carteira desinvestida
    (default 0.10 = menos de 10% dos ativos comprados).

    Retorna (df_por_ativo, df_carteira, df_exposicao_diaria).
    """
    if not series_por_hilo:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    por_ativo, carteira, diario = [], [], []

    for hilo in sorted(series_por_hilo):
        d = series_por_hilo[hilo]
        if not d:
            continue
        inv = pd.DataFrame({a: v["investido"] for a, v in d.items()}).sort_index()
        if excluir_suspeitos_agregados and ativos_suspeitos:
            inv = inv[[c for c in inv.columns if c not in ativos_suspeitos]]
        if inv.empty:
            continue
        idx = inv.index

        for a in inv.columns:
            s = inv[a]
            vivo = s.notna()
            if not vivo.any():
                continue
            sv = s.fillna(0.0).values > 0
            # so conta lacunas DENTRO do periodo em que o ativo existe
            p0, p1 = int(np.argmax(vivo.values)), len(sv) - int(np.argmax(vivo.values[::-1]))
            fora = ~sv[p0:p1]
            tam, di, df_ = _maior_sequencia(fora, idx[p0:p1])
            por_ativo.append({
                "HiLo_Fixo": int(hilo), "Ativo": a,
                "N_Barras_Vivas": int(p1 - p0),
                "Perc_Tempo_Comprado": float(sv[p0:p1].mean() * 100),
                "Maior_Lacuna_Barras": tam,
                "Maior_Lacuna_Meses": round(tam / 21.0, 1),
                "Lacuna_Inicio": di, "Lacuna_Fim": df_,
                "N_Lacunas_Acima_6m": int(sum(
                    1 for t, _, _ in [_maior_sequencia(fora, idx[p0:p1])] if t >= 126)),
            })

        # ---- carteira ----
        vivos = inv.notna().sum(axis=1)
        n_long = (inv.fillna(0.0) > 0).sum(axis=1)
        frac = (n_long / vivos.replace(0, np.nan)).fillna(0.0)
        for dt, nl, nv, fr in zip(idx, n_long.values, vivos.values, frac.values):
            diario.append({"HiLo_Fixo": int(hilo), "Data": dt,
                           "N_Ativos_Comprados": int(nl), "N_Ativos_Vivos": int(nv),
                           "Frac_Comprados": float(fr)})

        for lim in [0.0, limiar_exposicao_lacuna, 0.25, 0.50]:
            mask = (frac.values <= lim) if lim > 0 else (n_long.values == 0)
            tam, di, df_ = _maior_sequencia(mask, idx)
            carteira.append({
                "HiLo_Fixo": int(hilo),
                "Criterio": ("nenhum ativo comprado" if lim == 0
                             else f"<= {lim:.0%} dos ativos comprados"),
                "Maior_Sequencia_Barras": tam,
                "Maior_Sequencia_Meses": round(tam / 21.0, 1),
                "Inicio": di, "Fim": df_,
                "Perc_Barras_Nesse_Estado": float(mask.mean() * 100),
                "Frac_Comprados_Mediana": float(np.median(frac.values)),
                "Frac_Comprados_Minima": float(np.min(frac.values)),
            })

    return (pd.DataFrame(por_ativo), pd.DataFrame(carteira),
            pd.DataFrame(diario))

wf_resumos = []
hilos_metricas = []
diagnostico_dados = []
ativos_suspeitos = set()
ret_liq_por_hilo = {h: {} for h in hilos_fixos_janelas}
series_longonly = {h: {} for h in hilos_fixos_janelas}
wf_trocas_dfs = []
wf_curvas_dfs = []
resumo_graficos_wf = {}

if data_inicio_analise is not None or data_fim_analise is not None:
    print(f"RECORTE DE PERIODO: "
          f"{'de ' + str(data_inicio_analise.date()) if data_inicio_analise is not None else ''}"
          f"{' ate ' + str(data_fim_analise.date()) if data_fim_analise is not None else ''}")

_descartados_por_tamanho = []

for ticker in TICKERS:
    print(f"Processando {ticker}...")
    caminho_arquivo = os.path.join(dados_base, f"{ticker}.xlsx")

    if not os.path.exists(caminho_arquivo):
        print(f"Arquivo nao encontrado: {ticker}")
        continue

    try:
        df_base = preparar_dados(caminho_arquivo)

        if df_base is None or df_base.empty:
            print(f"{ticker}: base vazia ou insuficiente")
            continue

        pnl_por_hilo = {}
        ops_por_hilo = {}
        ultimo_df_bt = None

        for n_hilo in range(hilo_min, hilo_max + 1):
            df_bt = rodar_backtest_hilo_vetorizado(df_base, n_hilo)

            if df_bt is None or df_bt.empty:
                continue

            ultimo_df_bt = df_bt
            pnl_por_hilo[n_hilo] = df_bt["pnl"]
            ops_por_hilo[n_hilo] = df_bt[["trade_id", "trade_decision", "pnl"]].assign(Data=df_bt.index)

        if len(pnl_por_hilo) == 0:
            print(f"{ticker}: nenhum backtest valido")
            continue

        # holding (referencia)
        if ultimo_df_bt is not None and not ultimo_df_bt.empty:
            holding_total = (ultimo_df_bt["holding"].iloc[-1] / montante_inicial) - 1
            holding_aa = annualize_return(holding_total, len(ultimo_df_bt), 252)
        else:
            holding_total = np.nan
            holding_aa = np.nan

        mvd = float(df_base.attrs.get("max_var_diaria", np.nan))
        if len(df_base) < hilo_max + (dias_minimos_selecao or 0) + 5:
            _descartados_por_tamanho.append(ticker)
        n_ext = int(df_base.attrs.get("n_barras_extremas", 0))
        suspeito = bool(np.isfinite(mvd) and mvd > limiar_var_diaria_suspeita)
        if suspeito:
            ativos_suspeitos.add(ticker)
            print(f"  AVISO {ticker}: variacao diaria maxima de {mvd:.1%} em "
                  f"{str(df_base.attrs.get('data_max_var'))[:10]} ({n_ext} barra(s) "
                  f"acima de {limiar_var_diaria_suspeita:.0%}). Provavel preco nao "
                  f"ajustado — excluido das analises agregadas.")
        diagnostico_dados.append({
            "Ativo": ticker,
            "Max_Var_Diaria_Preco": mvd,
            "Data_Max_Var": df_base.attrs.get("data_max_var"),
            "N_Barras_Acima_Limiar": n_ext,
            "Limiar_Usado": limiar_var_diaria_suspeita,
            "Suspeito": suspeito,
        })

        # retorno diario liquido de custo dos hilos fixos avaliados nas
        # janelas moveis: o custo e debitado na barra de FECHAMENTO de cada
        # operacao, que e onde ele de fato ocorre.
        for hf in hilos_fixos_janelas:
            g = ops_por_hilo.get(hf)
            if hf not in pnl_por_hilo or g is None or g.empty:
                continue
            pnl_d = pnl_por_hilo[hf].astype(float).copy()
            gv = g.dropna(subset=["trade_id"])
            if not gv.empty:
                fech = gv.groupby("trade_id")["Data"].last()
                custo_ops = fech.value_counts().reindex(pnl_d.index).fillna(0.0)
                pnl_d = pnl_d - custo_ops * (custo_bps_janelas / 10000.0) * montante_inicial
            ret_liq_por_hilo[hf][ticker] = pnl_d / float(montante_inicial)

            # ---- series para a comparacao long-only vs buy-and-hold ----
            bt = rodar_backtest_hilo_vetorizado(df_base, hf)
            if bt is None or bt.empty:
                continue
            # direcao VIGENTE na barra anterior: e ela que gera o pnl da barra
            dir_ant = bt["trade_decision"].shift(1).fillna(0)
            custo_bar = pd.Series(0.0, index=bt.index)
            gv = bt.dropna(subset=["trade_id"])
            if not gv.empty:
                fe = gv.groupby("trade_id")["trade_decision"].agg(["first"])
                fe["data"] = gv.groupby("trade_id").apply(
                    lambda g: g.index[-1], include_groups=False)
                # custo so nas operacoes efetivamente realizadas
                for dcol, mask_nome in [("long", 1), ("todas", 0)]:
                    pass
                fech_todas = fe["data"].value_counts().reindex(bt.index).fillna(0.0)
                fech_long = (fe.loc[fe["first"] > 0, "data"].value_counts()
                             .reindex(bt.index).fillna(0.0))
                custo_bar = fech_todas * (custo_bps_janelas / 10000.0) * montante_inicial
                custo_long = fech_long * (custo_bps_janelas / 10000.0) * montante_inicial
            else:
                custo_long = custo_bar

            pnl_ls = bt["pnl"] - custo_bar
            pnl_lo = bt["pnl"].where(dir_ant > 0, 0.0) - custo_long
            series_longonly[hf][ticker] = {
                "long_short": (pnl_ls / montante_inicial).values,
                "long_only": (pnl_lo / montante_inicial).values,
                "buy_hold": bt["holding"].pct_change().fillna(0.0).values,
                "investido": (dir_ant > 0).astype(float).values,
            }
            for k in series_longonly[hf][ticker]:
                series_longonly[hf][ticker][k] = pd.Series(
                    series_longonly[hf][ticker][k], index=bt.index)

        met_hilos = montar_metricas_por_hilo(ticker, ops_por_hilo)
        if not met_hilos.empty:
            hilos_metricas.append(met_hilos)

        df_pnl_hilos = pd.DataFrame(pnl_por_hilo)

        resumo_wf, trocas_wf, curva_wf = rodar_walkforward_anual(
            ticker, df_pnl_hilos, ops_por_hilo
        )

        if resumo_wf is not None:
            resumo_wf["Rent_Total_Holding"] = holding_total
            resumo_wf["Rent_AA_Holding"] = holding_aa

            wf_resumos.append(resumo_wf)
            wf_trocas_dfs.append(trocas_wf)
            wf_curvas_dfs.append(curva_wf)

            if ultimo_df_bt is not None and not ultimo_df_bt.empty:
                resumo_graficos_wf[ticker] = {
                    "curva": curva_wf[["Data", "Curva_WF"]],
                    "holding": ultimo_df_bt["holding"],
                }

            print(f"{ticker}: processado com sucesso")
        else:
            print(f"{ticker}: sem resultado de walk-forward")

    except Exception as e:
        print(f"Erro em {ticker}: {e}")
        continue


# =========================
# P-VALOR DA ESTRATEGIA
# =========================
def _t_newey_west(x, lags=None):
    """
    t-statistic da media de x com erro-padrao Newey-West (HAC).

    Retornos de estrategia seguidora de tendencia sao autocorrelacionados
    (a posicao persiste por varias barras). O t ingenuo mean/(sd/sqrt(n))
    assume independencia e INFLA a significancia. Lag automatico pela
    regra de Newey-West: floor(4*(n/100)^(2/9)).
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30 or np.std(x) == 0:
        return np.nan, np.nan, np.nan
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 2))

    e = x - x.mean()
    gamma0 = float(e @ e) / n
    s2 = gamma0
    for L in range(1, lags + 1):
        gamma = float(e[L:] @ e[:-L]) / n
        s2 += 2.0 * (1.0 - L / (lags + 1.0)) * gamma
    if s2 <= 0:
        return np.nan, np.nan, np.nan

    se = np.sqrt(s2 / n)
    t = x.mean() / se
    p = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return float(t), float(p), int(lags)


def _p_bootstrap_bloco(x, n_boot=2000, bloco=21, seed=42):
    """
    p-valor bilateral por bootstrap de blocos circulares sob H0: media = 0.

    Reamostra blocos contiguos, preservando autocorrelacao e caudas gordas.
    Nao assume normalidade — relevante porque retornos de HiLo tem excesso
    de curtose alto.

    Calibracao verificada sob H0: rejeita ~2.5% a 5% nominal, ou seja, e
    CONSERVADOR. Erra para o lado de nao declarar significancia.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 100 or np.std(x) == 0:
        return np.nan

    rng = np.random.default_rng(seed)
    centrado = x - x.mean()                      # impoe H0
    n_blocos = int(np.ceil(n / bloco))
    obs = abs(x.mean() / (x.std(ddof=1) / np.sqrt(n)))

    inicios = rng.integers(0, n, size=(n_boot, n_blocos))
    desloc = np.arange(bloco)
    idx = (inicios[:, :, None] + desloc[None, None, :]).reshape(n_boot, -1) % n
    amostras = centrado[idx[:, :n]]

    m = amostras.mean(axis=1)
    s = amostras.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_boot = np.abs(m / (s / np.sqrt(n)))
    t_boot = t_boot[np.isfinite(t_boot)]
    if len(t_boot) == 0:
        return np.nan
    return float((1.0 + np.sum(t_boot >= obs)) / (1.0 + len(t_boot)))


def _sharpe_deflacionado(sharpe_aa, n_obs, n_trials, skew, kurt):
    """
    Probabilistic Sharpe Ratio deflacionado (Bailey & Lopez de Prado, 2014).

    Compara o Sharpe observado contra o MAXIMO esperado sob H0 em n_trials
    tentativas, corrigindo por assimetria e curtose.

    ATENCAO AO QUE ENTRA EM n_trials. Nao e o numero de hilos (99).
    O walk-forward ja neutraliza a busca ENTRE HILOS: o hilo e escolhido
    com dados ate T e o resultado e medido de T em diante, entao sob H0 o
    retorno futuro do hilo vencedor e nao-viesado. Simulacao de 500
    universos de ruido puro com 99 hilos e selecao anual por pnl acumulado
    confirmou: p ingenuo rejeitou em 5.6% a 5% nominal (calibrado).
    Usar n_trials=99 aqui pune duas vezes e reprova tudo por construcao.

    A busca que resta SEM protecao e a busca ENTRE ATIVOS: varrer N ativos
    e olhar o melhor. Por isso o default e o numero de ativos da amostra.

    n_trials=1 desliga a deflacao e recai no PSR simples contra zero — use
    quando a intencao for operar o universo inteiro, sem garimpar vencedor.

    Retorna (sharpe_esperado_sob_H0, p_valor_deflacionado).
    """
    if not np.isfinite(sharpe_aa) or n_obs < 100 or n_trials < 1:
        return np.nan, np.nan

    sr = sharpe_aa / np.sqrt(252.0)              # Sharpe por barra
    if n_trials == 1:
        sr0 = 0.0                                # sem penalidade: PSR contra zero
    else:
        gamma = 0.5772156649
        e_max = ((1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
                 + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e)))
        sr0 = e_max / np.sqrt(n_obs - 1.0)       # Sharpe maximo esperado sob H0

    den = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2
    if den <= 0:
        return float(sr0 * np.sqrt(252.0)), np.nan
    z = (sr - sr0) * np.sqrt(n_obs - 1.0) / np.sqrt(den)
    dsr = float(stats.norm.cdf(z))               # P(Sharpe verdadeiro > sr0)
    return float(sr0 * np.sqrt(252.0)), float(1.0 - dsr)


def _benjamini_hochberg(p):
    """q-valores de Benjamini-Hochberg (controle de FDR)."""
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(p)
    q = np.full(len(p), np.nan)
    if ok.sum() == 0:
        return q
    pv = p[ok]
    m = len(pv)
    ordem = np.argsort(pv)                       # p em ordem crescente
    escalado = pv[ordem] * m / np.arange(1, m + 1)
    ajust = np.minimum.accumulate(escalado[::-1])[::-1]   # cummin do maior p ao menor
    tmp = np.empty(m)
    tmp[ordem] = np.minimum(ajust, 1.0)
    q[ok] = tmp
    return q


def montar_aba_pvalor(wf_curvas_df, n_trials=None, n_boot=2000):
    """
    Constroi a aba "p valor":
      - uma linha por ativo, com o p-valor do retorno diario da estrategia;
      - linhas agregadas para o conjunto de todos os ativos.

    O agregado NAO e uma combinacao dos p-valores individuais: acoes
    brasileiras sao fortemente correlacionadas, e combinar p-valores
    assumindo independencia (Fisher, Stouffer) superestima grosseiramente
    a significancia. O teste correto e sobre a serie temporal da carteira
    equal-weight, que ja incorpora a correlacao cruzada.

    QUAL COLUNA USAR — depende do que se pretende fazer com o resultado:

    (A) OPERAR O UNIVERSO INTEIRO, sem escolher ativo:
        -> "TODOS (carteira equal-weight)" e as linhas SUBPERIODO.
        -> p_Bonferroni e p_Deflacionado_DSR NAO se aplicam: nao ha busca
           entre ativos se todos sao operados. Aplicar essas correcoes aqui
           e penalizar uma escolha que nao foi feita.

    (B) ESCOLHER UM OU POUCOS ATIVOS depois de olhar os 89:
        -> p_Bonferroni (conservador) ou q_BH_FDR (menos conservador).
        -> p_Deflacionado_DSR, com n_trials = numero de ativos varridos.

    Em ambos os casos: p_padrao, p_NeweyWest e p_Bootstrap_Bloco medem a mesma
    coisa por caminhos diferentes. Sob simulacao os tres deram praticamente
    igual nesta estrategia (o retorno diario "sinal x variacao" tem pouca
    autocorrelacao). Se divergirem, prefira p_Bootstrap_Bloco.
    """
    if wf_curvas_df is None or wf_curvas_df.empty:
        return pd.DataFrame()

    # n_trials default = numero de ativos avaliados (definido abaixo, apos
    # saber quantos ativos entraram). NAO usar o numero de hilos: ver a
    # docstring de _sharpe_deflacionado.

    df = wf_curvas_df.copy()
    df = df[df["HiLo_Vigente"].notna()]           # so barras com posicao
    if df.empty:
        return pd.DataFrame()

    linhas = []
    for ativo, g in df.groupby("Ativo"):
        x = pd.to_numeric(g["Ret_Diario_WF"], errors="coerce").dropna().values
        n = len(x)
        if n < 100:
            continue

        sd = x.std(ddof=1)
        sharpe_aa = (x.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan
        t_padrao = (x.mean() / (sd / np.sqrt(n))) if sd > 0 else np.nan
        p_padrao = 2.0 * (1.0 - stats.norm.cdf(abs(t_padrao))) if np.isfinite(t_padrao) else np.nan
        t_nw, p_nw, lags = _t_newey_west(x)
        p_boot = _p_bootstrap_bloco(x, n_boot=n_boot)
        sk = float(stats.skew(x))
        ku = float(stats.kurtosis(x, fisher=False))

        linhas.append({
            "Escopo": "Ativo",
            "Ativo": ativo,
            "N_Barras": n,
            "Anos": n / 252.0,
            "Ret_Medio_Diario": float(x.mean()),
            "Vol_AA": float(sd * np.sqrt(252)),
            "Sharpe_AA": sharpe_aa,
            "Assimetria": sk,
            "Curtose": ku,
            "t_Padrao": t_padrao,
            "p_Padrao": p_padrao,
            "t_NeweyWest": t_nw,
            "p_NeweyWest": p_nw,
            "NW_Lags": lags,
            "p_Bootstrap_Bloco": p_boot,
        })

    if len(linhas) == 0:
        return pd.DataFrame()

    res = pd.DataFrame(linhas)

    # busca sem protecao = varrer N ativos e olhar o melhor. n_trials default
    # e o numero de ativos que entraram, NAO o numero de hilos.
    if n_trials is None:
        n_trials = len(res)

    dsr = [
        _sharpe_deflacionado(sh, int(nn), n_trials, sk, ku)
        for sh, nn, sk, ku in zip(res["Sharpe_AA"], res["N_Barras"],
                                  res["Assimetria"], res["Curtose"])
    ]
    res["Sharpe_Esperado_H0_MaxTrials"] = [a for a, _ in dsr]
    res["p_Deflacionado_DSR"] = [b for _, b in dsr]
    res["N_Trials_Ativos"] = n_trials

    # correcoes para multiplos testes entre ativos
    n_ativos = len(res)
    res["p_Bonferroni"] = np.minimum(res["p_Padrao"] * n_ativos, 1.0)
    res["q_BH_FDR"] = _benjamini_hochberg(res["p_Padrao"].values)
    res = res.sort_values("p_Padrao").reset_index(drop=True)

    # ordem de leitura: identificacao, descritivas, p-valor principal,
    # verificacoes de robustez, correcoes para multiplos testes.
    ordem = [
        "Escopo", "Ativo", "N_Barras", "Anos",
        "Ret_Medio_Diario", "Vol_AA", "Sharpe_AA", "Assimetria", "Curtose",
        "t_Padrao", "p_Padrao",
        "t_NeweyWest", "p_NeweyWest", "NW_Lags", "p_Bootstrap_Bloco",
        "p_Bonferroni", "q_BH_FDR",
        "Sharpe_Esperado_H0_MaxTrials", "p_Deflacionado_DSR", "N_Trials_Ativos",
    ]
    res = res[[c for c in ordem if c in res.columns]
              + [c for c in res.columns if c not in ordem]]

    # ---------- agregado: carteira equal-weight ----------
    piv = df.pivot_table(index="Data", columns="Ativo", values="Ret_Diario_WF")
    port = piv.mean(axis=1).dropna()
    agregados = []

    if len(port) >= 100:
        xp = port.values
        sdp = xp.std(ddof=1)
        sh_p = (xp.mean() / sdp * np.sqrt(252)) if sdp > 0 else np.nan
        t_ip = xp.mean() / (sdp / np.sqrt(len(xp)))
        p_ip = 2.0 * (1.0 - stats.norm.cdf(abs(t_ip)))
        t_np, p_np, lg = _t_newey_west(xp)
        p_bp = _p_bootstrap_bloco(xp, n_boot=n_boot)
        skp = float(stats.skew(xp))
        kup = float(stats.kurtosis(xp, fisher=False))
        sr0p, p_dp = _sharpe_deflacionado(sh_p, len(xp), n_trials, skp, kup)

        agregados.append({
            "Escopo": "TODOS (carteira equal-weight)",
            "Ativo": f"{piv.shape[1]} ativos",
            "N_Barras": len(xp),
            "Anos": len(xp) / 252.0,
            "Ret_Medio_Diario": float(xp.mean()),
            "Vol_AA": float(sdp * np.sqrt(252)),
            "Sharpe_AA": sh_p,
            "Assimetria": skp,
            "Curtose": kup,
            "t_Padrao": float(t_ip),
            "p_Padrao": float(p_ip),
            "t_NeweyWest": t_np,
            "p_NeweyWest": p_np,
            "NW_Lags": lg,
            "p_Bootstrap_Bloco": p_bp,
            "Sharpe_Esperado_H0_MaxTrials": sr0p,
            "p_Deflacionado_DSR": p_dp,
            "N_Trials_Ativos": n_trials,
        })

        # o teste de secao transversal sobre os Sharpes individuais assume
        # independencia entre ativos, o que e falso. Reporta-se o N efetivo
        # implicado pela correlacao media entre as series de retorno.
        corr = piv.corr().values
        tri = corr[np.triu_indices_from(corr, k=1)]
        rho = float(np.nanmean(tri)) if len(tri) else np.nan
        sh = res["Sharpe_AA"].dropna().values

        if len(sh) > 2 and np.isfinite(rho):
            n_eff = len(sh) / (1.0 + (len(sh) - 1) * max(rho, 0.0))
            t_cs = sh.mean() / (sh.std(ddof=1) / np.sqrt(len(sh)))
            t_ef = sh.mean() / (sh.std(ddof=1) / np.sqrt(n_eff))
            agregados.append({
                "Escopo": "TODOS (secao transversal dos Sharpes)",
                "Ativo": f"{len(sh)} ativos | corr media {rho:.3f} | N_efetivo {n_eff:.1f}",
                "N_Barras": len(sh),
                "Sharpe_AA": float(sh.mean()),
                "t_Padrao": float(t_cs),
                "p_Padrao": float(2 * (1 - stats.norm.cdf(abs(t_cs)))),
                "t_NeweyWest": float(t_ef),
                "p_NeweyWest": float(2 * (1 - stats.norm.cdf(abs(t_ef)))),
                "N_Trials_Ativos": n_trials,
            })

        # ---------- estabilidade: o resultado agregado sobrevive por subperiodo? ----------
        # Teste que mais discrimina: um t global respeitavel pode vir quase
        # inteiro de um unico regime favoravel. Se a estrategia realmente se
        # adapta a cenarios diferentes, o sinal deve aparecer em varios blocos.
        anos_idx = port.index.year
        a0, a1 = int(anos_idx.min()), int(anos_idx.max())
        for ini in range(a0, a1 + 1, anos_por_bloco_pvalor):
            fim = min(ini + anos_por_bloco_pvalor - 1, a1)
            seg = port[(anos_idx >= ini) & (anos_idx <= fim)]
            if len(seg) < 250:
                continue
            sseg = seg.std(ddof=1)
            if sseg <= 0:
                continue
            t_s = seg.mean() / (sseg / np.sqrt(len(seg)))
            agregados.append({
                "Escopo": f"SUBPERIODO {ini}-{fim} (carteira equal-weight)",
                "Ativo": f"{piv.shape[1]} ativos",
                "N_Barras": len(seg),
                "Anos": len(seg) / 252.0,
                "Ret_Medio_Diario": float(seg.mean()),
                "Vol_AA": float(sseg * np.sqrt(252)),
                "Sharpe_AA": float(seg.mean() / sseg * np.sqrt(252)),
                "t_Padrao": float(t_s),
                "p_Padrao": float(2 * (1 - stats.norm.cdf(abs(t_s)))),
            })

        # ---------- consistencia do sinal entre ativos ----------
        # Se o resultado vem de um punhado de vencedores, a fracao de ativos
        # com Sharpe > 0 fica perto de 50%. Se a estrategia funciona na media
        # do universo, fica significativamente acima.
        sh_val = res["Sharpe_AA"].dropna().values
        if len(sh_val) >= 5:
            n_pos = int((sh_val > 0).sum())
            p_bin = float(stats.binomtest(n_pos, len(sh_val), 0.5).pvalue)
            agregados.append({
                "Escopo": "TODOS (teste binomial do sinal do Sharpe)",
                "Ativo": f"{n_pos} de {len(sh_val)} ativos com Sharpe > 0",
                "N_Barras": n_pos,
                "Sharpe_AA": float(np.median(sh_val)),
                "p_Padrao": p_bin,
            })

        # ---------- diagnostico de diversificacao ----------
        # Sharpe agregado observado vs o esperado se cada ativo tivesse o
        # Sharpe mediano e a correlacao media medida. Distancia grande indica
        # que o agregado depende de poucos ativos.
        if np.isfinite(rho) and piv.shape[1] > 1:
            N = piv.shape[1]
            ganho = np.sqrt(N / (1.0 + (N - 1) * max(rho, 0.0)))
            esperado = float(np.median(sh_val)) * ganho if len(sh_val) else np.nan
            agregados.append({
                "Escopo": "TODOS (diagnostico de diversificacao)",
                "Ativo": (f"corr media {rho:.3f} | ganho teorico {ganho:.2f}x | "
                          f"Sharpe esperado {esperado:.3f} vs observado {sh_p:.3f}"),
                "N_Barras": N,
                "Sharpe_AA": esperado,
            })

    # contagens de quantos ativos passam em cada criterio
    for rot, col, lim in [
        ("RESUMO: ativos com p_Padrao < 0.05", "p_Padrao", 0.05),
        ("RESUMO: ativos com p_NeweyWest < 0.05", "p_NeweyWest", 0.05),
        ("RESUMO: ativos com p_Bootstrap < 0.05", "p_Bootstrap_Bloco", 0.05),
        ("RESUMO: ativos com q_BH_FDR < 0.10", "q_BH_FDR", 0.10),
        ("RESUMO: ativos com p_Bonferroni < 0.05", "p_Bonferroni", 0.05),
        ("RESUMO: ativos com p_Deflacionado_DSR < 0.05", "p_Deflacionado_DSR", 0.05),
    ]:
        if col in res.columns:
            agregados.append({
                "Escopo": rot,
                "Ativo": f"{int((res[col] < lim).sum())} de {n_ativos}",
                "N_Barras": int((res[col] < lim).sum()),
            })
    agregados.append({
        "Escopo": "RESUMO: falsos positivos esperados ao acaso (p<0.05)",
        "Ativo": f"{0.05 * n_ativos:.1f} de {n_ativos}",
        "N_Barras": 0.05 * n_ativos,
    })

    saida = pd.concat([res, pd.DataFrame(agregados)], ignore_index=True)
    return saida[[c for c in res.columns] +
                 [c for c in saida.columns if c not in res.columns]]




# =========================
# CARTEIRA WALK-FORWARD (selecao de ATIVOS)
# =========================
def montar_carteira_wf(wf_curvas_df):
    """
    Carteira equal-weight com selecao de ATIVOS em walk-forward.

    Em cada data de rebalanceamento (mesma periodicidade de "meses_selecao"):
      1) calcula, para CADA ativo, a esperanca da estrategia WF acumulada
         desde o inicio ATE aquela data — usando somente operacoes ENCERRADAS;
      2) seleciona os ativos com esperanca > "limiar_esperanca_carteira" e com
         pelo menos "operacoes_minimas_carteira" operacoes encerradas;
      3) opera esses ativos com peso igual ate o proximo rebalanceamento.
      4) se nenhum ativo qualificar, a carteira fica em caixa (retorno zero).

    A esperanca aqui e a mesma formula de Esperanca_WF (multiplos de R):
        payoff * p - (1 - p),  payoff = ganho_medio / |perda_media|
    o que a torna diretamente comparavel a coluna do WF_Resumo.

    DIFERENCA CRUCIAL PARA O FILTRO MANUAL NA PLANILHA: filtrar por
    Esperanca_WF do WF_Resumo usa o valor do FIM do periodo, ou seja, escolhe
    os ativos que se sabe terem dado certo. Aqui a esperanca e recalculada a
    cada rebalanceamento com informacao disponivel naquela data. A diferenca
    entre as duas curvas e o tamanho do vies de selecao.

    Retorna (df_diario, df_resumo, df_rebalanceamentos).
    """
    if wf_curvas_df is None or wf_curvas_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    obrig = ["Ops_Ganho", "Pnl_Ganhos", "Ops_Perda", "Pnl_Perdas", "Ops_Fechadas"]
    if any(c not in wf_curvas_df.columns for c in obrig):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    c = wf_curvas_df.copy()
    c = c[c["HiLo_Vigente"].notna()]
    if c.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ret = c.pivot_table(index="Data", columns="Ativo", values="Ret_Diario_WF").sort_index()
    idx = ret.index

    def acum(col):
        return (c.pivot_table(index="Data", columns="Ativo", values=col, aggfunc="sum")
                 .reindex(index=idx, columns=ret.columns).fillna(0.0).cumsum())

    n_ops = acum("Ops_Fechadas")
    n_win = acum("Ops_Ganho")
    s_win = acum("Pnl_Ganhos")
    n_los = acum("Ops_Perda")
    s_los = acum("Pnl_Perdas")

    with np.errstate(invalid="ignore", divide="ignore"):
        p_acerto = n_win / n_ops.where(n_ops > 0)
        ganho_med = s_win / n_win.where(n_win > 0)
        perda_med = (s_los / n_los.where(n_los > 0)).abs()
        payoff = ganho_med / perda_med.where(perda_med > 0)
        esperanca = payoff * p_acerto - (1.0 - p_acerto)

    # ativo so e elegivel nas barras em que a estrategia esta posicionada nele
    ativo_vivo = c.pivot_table(index="Data", columns="Ativo", values="HiLo_Vigente",
                               aggfunc="last").reindex(index=idx, columns=ret.columns).notna()

    datas_rebal = primeiras_datas_meses(idx, meses_selecao)
    pesos = pd.DataFrame(0.0, index=idx, columns=ret.columns)
    rebals = []

    for data_r in datas_rebal:
        pos = idx.get_loc(data_r)
        elegivel = (
            (n_ops.iloc[pos] >= operacoes_minimas_carteira)
            & (esperanca.iloc[pos] > limiar_esperanca_carteira)
            & ativo_vivo.iloc[pos]
        )
        escolhidos = list(ret.columns[elegivel.fillna(False).values])
        fim = len(idx) - 1
        prox = [idx.get_loc(d) for d in datas_rebal if idx.get_loc(d) > pos]
        if prox:
            fim = prox[0]

        if escolhidos and pos + 1 <= fim:
            # ATENCAO: pesos.iloc[a:b][cols] = x e atribuicao ENCADEADA e nao
            # tem efeito sob Copy-on-Write (pandas >= 3.0) — falha em silencio.
            # A atribuicao precisa ser em um passo unico com .loc.
            pesos.loc[idx[pos + 1:fim + 1], escolhidos] = 1.0 / len(escolhidos)

        rebals.append({
            "Data_Rebalanceamento": data_r,
            "Qtd_Ativos_Elegiveis": len(escolhidos),
            "Qtd_Ativos_Avaliados": int(ativo_vivo.iloc[pos].sum()),
            "Esperanca_Mediana_Elegiveis": (float(esperanca.iloc[pos][escolhidos].median())
                                            if escolhidos else np.nan),
            "Ativos": ", ".join(escolhidos) if escolhidos else "(caixa)",
        })

    # peso so vale onde ha retorno; renormaliza para somar 1 nas barras validas
    pesos = pesos.where(ret.notna(), 0.0)
    soma = pesos.sum(axis=1)
    pesos_n = pesos.div(soma.where(soma > 0), axis=0).fillna(0.0)

    ret_carteira = (pesos_n * ret.fillna(0.0)).sum(axis=1)
    ret_carteira = ret_carteira.where(soma > 0, 0.0)
    curva = montante_inicial * (1.0 + ret_carteira).cumprod()

    # referencia: equal-weight de TODOS os ativos, sem selecao
    ret_todos = ret.mean(axis=1).fillna(0.0)
    curva_todos = montante_inicial * (1.0 + ret_todos).cumprod()

    # TETO NAO IMPLEMENTAVEL: mesma regra de esperanca, mas usando a esperanca
    # do FIM DO PERIODO. Equivale a filtrar a coluna Esperanca_WF do WF_Resumo
    # direto na planilha. Nao e uma estrategia — para montar essa carteira na
    # primeira data seria preciso conhecer o resultado dos anos seguintes, e
    # varios dos ativos escolhidos sequer estavam listados na epoca.
    # Serve como LIMITE SUPERIOR: qualquer regra implementavel fica abaixo.
    esp_final = esperanca.iloc[-1]
    ops_final = n_ops.iloc[-1]
    look = [a for a in ret.columns
            if np.isfinite(esp_final.get(a, np.nan))
            and esp_final[a] > limiar_esperanca_carteira
            and ops_final.get(a, 0) >= operacoes_minimas_carteira]
    if look:
        ret_look = ret[look].mean(axis=1).fillna(0.0)
    else:
        ret_look = pd.Series(0.0, index=idx)
    curva_look = montante_inicial * (1.0 + ret_look).cumprod()
    m_look = ativo_vivo.reindex(index=idx, columns=ret.columns).fillna(False).copy()
    m_look.loc[:, [a for a in ret.columns if a not in look]] = False
    m_look = m_look.values

    diario = pd.DataFrame({
        "Data": idx,
        "Qtd_Ativos_Carteira": (pesos_n > 0).sum(axis=1).values,
        "Ret_Diario_Carteira": ret_carteira.values,
        "Curva_Carteira": curva.values,
        "Ret_Diario_Todos": ret_todos.values,
        "Curva_Todos": curva_todos.values,
        "Ret_Diario_LookAhead": ret_look.values,
        "Curva_LookAhead": curva_look.values,
    })

    # TESTE PAREADO — a pergunta que o p-valor isolado de cada carteira nao
    # responde: a SELECAO adiciona alguma coisa? H0: retorno da carteira
    # selecionada = retorno da carteira sem selecao. Testa-se a serie da
    # diferenca, que elimina o fator de mercado comum as duas e por isso tem
    # muito mais poder do que comparar dois p-valores separados.
    dif = (ret_carteira - ret_todos).dropna()
    linha_dif = {}
    if len(dif) > 30 and dif.std(ddof=1) > 0:
        sd_d = float(dif.std(ddof=1))
        t_d = float(dif.mean() / (sd_d / np.sqrt(len(dif))))
        t_dnw, p_dnw, _ = _t_newey_west(dif.values)
        linha_dif = {
            "Carteira": "DIFERENCA (selecionada - todos)",
            "Metrica": "Teste pareado",
            "N_Barras": len(dif),
            "Anos": len(dif) / 252.0,
            "Rent_AA_Geometrica": float(dif.mean() * 252 * 100.0),
            "Vol_AA": sd_d * np.sqrt(252) * 100.0,
            "t_Padrao": t_d,
            "p_Padrao": float(2 * (1 - stats.norm.cdf(abs(t_d)))),
            "t_NeweyWest": t_dnw, "p_NeweyWest": p_dnw,
            "p_Bootstrap_Bloco": _p_bootstrap_bloco(dif.values, n_boot=n_boot_pvalor),
        }

    m_sel = (pesos_n > 0).reindex(index=idx, columns=ret.columns).fillna(False).values
    m_all = ativo_vivo.reindex(index=idx, columns=ret.columns).fillna(False).values

    ops_sel = _stats_operacoes_carteira(c, ret, m_sel,
                                        "Carteira WF (selecao por esperanca)")
    ops_all = _stats_operacoes_carteira(c, ret, m_all,
                                        "Referencia: todos os ativos")
    ops_look = _stats_operacoes_carteira(c, ret, m_look,
                                         "TETO look-ahead (NAO implementavel)")

    partes = [
        _metricas_carteira(ret_carteira, curva, "Carteira WF (selecao por esperanca)"),
        pd.DataFrame([ops_sel]) if ops_sel else pd.DataFrame(),
        _metricas_carteira(ret_todos, curva_todos, "Referencia: todos os ativos"),
        pd.DataFrame([ops_all]) if ops_all else pd.DataFrame(),
        _metricas_carteira(ret_look, curva_look, "TETO look-ahead (NAO implementavel)"),
        pd.DataFrame([ops_look]) if ops_look else pd.DataFrame(),
    ]
    partes = [x for x in partes if not x.empty]
    if linha_dif:
        partes.append(pd.DataFrame([linha_dif]))
    resumo = pd.concat(partes, ignore_index=True)

    df_rebal = pd.DataFrame(rebals)
    if look:
        df_rebal = pd.concat([df_rebal, pd.DataFrame([{
            "Data_Rebalanceamento": pd.NaT,
            "Qtd_Ativos_Elegiveis": len(look),
            "Qtd_Ativos_Avaliados": int(ret.shape[1]),
            "Esperanca_Mediana_Elegiveis": float(esp_final[look].median()),
            "Ativos": "TETO look-ahead (esperanca do FIM do periodo): " + ", ".join(look),
        }])], ignore_index=True)

    return diario, resumo, df_rebal


def _stats_operacoes_carteira(c, ret, mascara, rotulo):
    """
    Taxa de acerto, profit factor e esperanca de uma carteira.

    A carteira nao tem operacoes proprias — ela carrega varios ativos ao mesmo
    tempo. A definicao usada aqui e agregar as operacoes INDIVIDUAIS dos ativos
    enquanto estavam na carteira, atribuindo cada trade ao periodo pela sua
    DATA DE FECHAMENTO (mesma convencao do resto do codigo).

    ESCALA: cada operacao roda com notional fixo de "montante_inicial", entao
    Expec_Mat e Ganho/Perda medios sao R$ POR OPERACAO sobre 10k — comparaveis
    ao Expec_Mat_WF de cada ativo, e NAO o P&L em dinheiro da carteira, que
    depende do peso 1/N de cada posicao.

    profit_factor = soma dos ganhos / |soma das perdas|. Relaciona-se com as
    outras metricas por  PF = payoff * p / (1 - p).
    """
    cols = ["Ops_Fechadas", "Ops_Ganho", "Pnl_Ganhos", "Ops_Perda", "Pnl_Perdas"]
    if any(cc not in c.columns for cc in cols):
        return {}

    tot = {}
    for cc in cols:
        piv = (c.pivot_table(index="Data", columns="Ativo", values=cc, aggfunc="sum")
                 .reindex(index=ret.index, columns=ret.columns).fillna(0.0))
        tot[cc] = float((piv.values * mascara).sum())

    n_ops = tot["Ops_Fechadas"]
    if n_ops <= 0:
        return {}

    n_win, n_los = tot["Ops_Ganho"], tot["Ops_Perda"]
    s_win, s_los = tot["Pnl_Ganhos"], tot["Pnl_Perdas"]

    p_acerto = n_win / n_ops
    ganho_med = s_win / n_win if n_win > 0 else np.nan
    perda_med = abs(s_los / n_los) if n_los > 0 else np.nan
    payoff = ganho_med / perda_med if perda_med and perda_med > 0 else np.nan
    profit_factor = s_win / abs(s_los) if s_los != 0 else np.nan
    esperanca = payoff * p_acerto - (1.0 - p_acerto) if np.isfinite(payoff) else np.nan
    # esperanca em R$: media direta do pnl das operacoes, sem reconstruir por
    # taxa de acerto (evita o vies quando existem trades de pnl exatamente zero)
    expec_mat = (s_win + s_los) / n_ops

    return {
        "Carteira": rotulo, "Metrica": "Operacoes",
        "Total_Operacoes": int(n_ops),
        "Ops_Ganho": int(n_win), "Ops_Perda": int(n_los),
        "Taxa_Acerto": p_acerto * 100.0,
        "Ganho_Medio": ganho_med, "Perda_Media": -perda_med,
        "Payoff": payoff,
        "Profit_Factor": profit_factor,
        "Esperanca_R": esperanca,
        "Expec_Mat": expec_mat,
    }


def _metricas_carteira(ret_serie, curva, rotulo):
    """Metricas da carteira + percentual de janelas moveis positivas."""
    r_inv = ret_serie[ret_serie != 0.0]
    n = len(ret_serie)
    linhas = []

    sd = float(ret_serie.std(ddof=1))
    geo = float(curva.iloc[-1] / montante_inicial) ** (252.0 / n) - 1.0 if n > 0 else np.nan
    sh = float(ret_serie.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan
    t = float(ret_serie.mean() / (sd / np.sqrt(n))) if sd > 0 else np.nan
    dd = float((curva / curva.cummax() - 1.0).min())

    # bateria completa de p-valores, mesma da aba "p valor":
    # p_Padrao e o principal; NW e bootstrap sao verificacao de robustez.
    t_nw, p_nw, _ = _t_newey_west(ret_serie.values)
    p_boot = _p_bootstrap_bloco(ret_serie.values, n_boot=n_boot_pvalor)

    linhas.append({
        "Carteira": rotulo, "Metrica": "Resumo",
        "N_Barras": n, "Anos": n / 252.0,
        "Rent_Total": float(curva.iloc[-1] / montante_inicial - 1.0),
        "Rent_AA_Geometrica": geo * 100.0,
        "Vol_AA": sd * np.sqrt(252) * 100.0,
        "Sharpe": sh, "t_Padrao": t,
        "p_Padrao": float(2 * (1 - stats.norm.cdf(abs(t)))) if np.isfinite(t) else np.nan,
        "t_NeweyWest": t_nw, "p_NeweyWest": p_nw,
        "p_Bootstrap_Bloco": p_boot,
        "Drawdown_Max": dd * 100.0,
        "Perc_Barras_Investido": float(len(r_inv) / n) if n else np.nan,
    })

    # ATENCAO: janelas moveis sao SOBREPOSTAS. 5000 janelas de 30 dias vem de
    # ~250 janelas independentes; o percentual e informativo, mas o numero de
    # linhas NAO e o tamanho amostral. A coluna Janelas_Independentes da a
    # ordem de grandeza correta.
    for w in janelas_carteira:
        rr = (curva / curva.shift(w) - 1.0).dropna()
        if rr.empty:
            continue
        linhas.append({
            "Carteira": rotulo, "Metrica": f"Janelas de {w} dias",
            "N_Barras": len(rr),
            "Janelas_Independentes": int(n / w),
            "Qtd_Positivas": int((rr > 0).sum()),
            "Perc_Positivas": float((rr > 0).mean() * 100.0),
            "Retorno_Mediano": float(rr.median() * 100.0),
            "Retorno_Min": float(rr.min() * 100.0),
            "Retorno_Max": float(rr.max() * 100.0),
        })
    return pd.DataFrame(linhas)


# =========================
# RESULTADOS FINAIS (APENAS WF)
# =========================
wf_resumo_df = pd.DataFrame(wf_resumos)

if len(wf_trocas_dfs) > 0:
    wf_trocas_df = pd.concat(wf_trocas_dfs, ignore_index=True)
else:
    wf_trocas_df = pd.DataFrame(columns=[
        "Ativo", "Data_Selecao", "HiLo_Escolhido", "Origem_Selecao", "Motivo",
        "p_Unilateral_Escolhido",
        "t_Escolhido", "Sharpe_AA_Escolhido", "N_Barras_Escolhido",
        "Payoff_Escolhido", "Payoff_Ajustado_Escolhido",
        "Inclinacao_Payoff_vs_logHilo", "ProfitFactor_Escolhido", "Taxa_Acerto_Escolhido",
        "Expec_Escolhido", "Ops_Acum_Escolhido", "Rank_t_Escolhido",
        "Qtd_Finalistas", "Pnl_Acum_HiLo_Escolhido",
        "Qtd_Janelas_Avaliadas", "Data_Inicio_Vigencia", "Data_Fim_Vigencia",
        "Dias_Vigencia", "Rent_Trecho"
    ])

if len(wf_curvas_dfs) > 0:
    wf_curvas_df = pd.concat(wf_curvas_dfs, ignore_index=True)
else:
    wf_curvas_df = pd.DataFrame(columns=[
        "Ativo", "Data", "HiLo_Vigente", "Pnl_Diario_WF", "Ret_Diario_WF", "Curva_WF",
        "Ops_Fechadas", "Pnl_Ops_Fechadas", "Ops_Ganho", "Pnl_Ganhos",
        "Ops_Perda", "Pnl_Perdas"
    ])

if not wf_resumo_df.empty:
    wf_resumo_df = wf_resumo_df.sort_values(["Ativo"]).reset_index(drop=True)
    wf_trocas_df = wf_trocas_df.sort_values(["Ativo", "Data_Selecao"]).reset_index(drop=True)
    wf_curvas_df = wf_curvas_df.sort_values(["Ativo", "Data"]).reset_index(drop=True)

    print("Calculando p-valores...")
    wf_pvalor_df = montar_aba_pvalor(wf_curvas_df, n_boot=n_boot_pvalor)

    hilos_metricas_df = (pd.concat(hilos_metricas, ignore_index=True)
                         if hilos_metricas else pd.DataFrame())

    print("Montando carteira walk-forward...")
    cart_diario, cart_resumo, cart_rebal = montar_carteira_wf(wf_curvas_df)

    with pd.ExcelWriter(arquivo_saida, engine="openpyxl") as writer:
        wf_resumo_df.to_excel(writer, index=False, sheet_name="WF_Resumo")
        wf_trocas_df.to_excel(writer, index=False, sheet_name="WF_Trocas")
        wf_curvas_df.to_excel(writer, index=False, sheet_name="WF_Curvas")
        if not wf_pvalor_df.empty:
            wf_pvalor_df.to_excel(writer, index=False, sheet_name="p valor")
        if diagnostico_dados:
            pd.DataFrame(diagnostico_dados).sort_values(
                "Max_Var_Diaria_Preco", ascending=False).to_excel(
                writer, index=False, sheet_name="Dados_Suspeitos")
        if not hilos_metricas_df.empty:
            hilos_metricas_df.to_excel(writer, index=False, sheet_name="Hilos_Metricas")
            hilos_agregado_df = montar_agregado_por_hilo(hilos_metricas_df)
            if not hilos_agregado_df.empty:
                hilos_agregado_df.to_excel(writer, index=False,
                                           sheet_name="Hilos_Agregado")
            lac_at, lac_ct, lac_di = montar_lacunas_long(series_longonly)
            if not lac_ct.empty:
                lac_ct.to_excel(writer, index=False, sheet_name="Lacunas_Carteira")
                lac_at.to_excel(writer, index=False, sheet_name="Lacunas_Por_Ativo")
                lac_di.to_excel(writer, index=False, sheet_name="Exposicao_Long_Diaria")

            lo_sub = montar_longonly_subamostras(series_longonly)
            if not lo_sub.empty:
                lo_sub.to_excel(writer, index=False, sheet_name="LongOnly_Subamostras")

            lo_df, lo_diario, lo_testes = montar_longonly_vs_bh(series_longonly)
            if not lo_df.empty:
                lo_df.to_excel(writer, index=False, sheet_name="LongOnly_vs_BH")
            if not lo_testes.empty:
                lo_testes.to_excel(writer, index=False, sheet_name="LongOnly_Testes")
            if not lo_diario.empty:
                lo_diario.to_excel(writer, index=False, sheet_name="LongOnly_Diario")

            jan_df = montar_janelas_hilo_fixo(
                {h: pd.DataFrame(v) for h, v in ret_liq_por_hilo.items() if v})
            if not jan_df.empty:
                jan_df.to_excel(writer, index=False, sheet_name="Janelas_Hilo_Fixo")

            sim_curva, sim_resumo = montar_carteiras_aleatorias(hilos_metricas_df)
            if not sim_resumo.empty:
                sim_resumo.to_excel(writer, index=False,
                                    sheet_name="Carteiras_Aleat_Resumo")
                sim_curva.to_excel(writer, index=False,
                                   sheet_name="Carteiras_Aleatorias")
        if not cart_resumo.empty:
            cart_resumo.to_excel(writer, index=False, sheet_name="Carteira_Resumo")
            cart_rebal.to_excel(writer, index=False, sheet_name="Carteira_Rebal")
            cart_diario.to_excel(writer, index=False, sheet_name="Carteira_WF")

        print(f"Arquivo salvo com sucesso: {arquivo_saida}")
else:
    print("Nenhum resultado foi gerado.")