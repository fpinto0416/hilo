# -*- coding: utf-8 -*-
"""Motor do backtest de call ATM rolada sobre o sinal HiLo-50 long-only."""
import sqlite3, numpy as np, pandas as pd, os, warnings
warnings.filterwarnings("ignore")

DB_OPC = "/app/volatilidade_implicita/vol_implicita.db"
DB_ACAO = "/app/projeto_MIA26/database"
HILO_N = 50
DC_ENTRADA_MIN = 20   # so entra em vencimento com mais de 20 dias corridos
DC_ROLA = 10          # rola quando faltar menos de 10 dias corridos

def con():
    return sqlite3.connect(f"file:{DB_OPC}?mode=ro", uri=True)

# ---------- sinal ----------
def sinal_hilo(ticker, n=HILO_N):
    """Long-only, convencao do projeto_hilo.py (shift(1), Close do dia)."""
    p = f"{DB_ACAO}/{ticker}.xlsx"
    if not os.path.exists(p):
        return None
    d = pd.read_excel(p, index_col=0, parse_dates=True).sort_index()
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    d = d[~d.index.duplicated(keep="first")]
    d["hi"] = d["High"].rolling(n).mean().shift(1)
    d["lo"] = d["Low"].rolling(n).mean().shift(1)
    s = np.where(d["Close"] > d["hi"], 1, np.where(d["Close"] < d["lo"], -1, 0))
    pos = pd.Series(s, index=d.index).replace(0, np.nan).ffill().fillna(0)
    # long-only: -1 vira caixa
    d["long"] = (pos > 0).astype(int)
    return d[["Close", "long"]]

def episodios(sig):
    """Lista de (data_entrada, data_saida) em que o sinal esta comprado.
    Entra no fechamento do dia em que 'long' vira 1; sai no fechamento do
    dia em que volta a 0 (mesma convencao do backtest de acao)."""
    L = sig["long"].values
    idx = sig.index
    eps = []
    i = 0
    while i < len(L):
        if L[i] == 1 and (i == 0 or L[i-1] == 0):
            j = i
            while j + 1 < len(L) and L[j+1] == 1:
                j += 1
            # saida no dia seguinte ao ultimo dia comprado (quando zera)
            fim = idx[j+1] if j + 1 < len(L) else idx[j]
            eps.append((idx[i], fim))
            i = j + 1
        else:
            i += 1
    return eps

# ---------- opcoes ----------
def carregar_opcoes(ticker):
    c = con()
    mens = pd.read_sql(
        'select distinct vencimento from option_quote '
        'where ticker_ativo=? and tipo="C" and semanal=0', c, params=(ticker,))
    mensais = set(mens["vencimento"])
    iv = pd.read_sql(
        'select data,codneg,strike,vencimento,preco,fonte_preco,du,dc,iv,delta,forward '
        'from option_iv where ticker_ativo=? and tipo="C"', c, params=(ticker,))
    c.close()
    if iv.empty:
        return None
    iv = iv[iv["vencimento"].isin(mensais)].copy()
    iv = iv[(iv["preco"] > 0) & iv["forward"].notna()]
    iv["data"] = pd.to_datetime(iv["data"])
    iv["venc"] = pd.to_datetime(iv["vencimento"])
    return iv

TOL_DELTA = 0.20   # |delta-0.5| maximo para o contrato ser aceito como ATM

def escolher_call(iv, data, dc_min, tol=TOL_DELTA):
    """Call ATM do 1o vencimento mensal com mais de dc_min dias corridos,
    entre as que NEGOCIARAM no dia.

    A call escolhida e a de delta mais proximo de 0,5 -- nao a de strike mais
    proximo do forward. Motivo: como so entram contratos que negociaram, em
    dia ralo o strike mais proximo do forward pode ainda estar muito longe
    do dinheiro (visto de verdade: 2010-12-27, PETRA4, delta 0,009 escolhido
    como "ATM"). Se nenhum contrato do vencimento cair dentro de tol, tenta o
    vencimento seguinte; se nenhum servir, devolve None e o episodio e
    contado como sem call negociavel.
    """
    d = iv[(iv["data"] == data) & (iv["dc"] > dc_min)]
    if d.empty:
        return None
    d = d[d["delta"].notna()]
    for venc in sorted(d["venc"].unique()):
        dv = d[d["venc"] == venc]
        j = (dv["delta"] - 0.5).abs().idxmin()
        if abs(dv.loc[j, "delta"] - 0.5) <= tol:
            return dv.loc[j]
    return None

def preco_em(iv, codneg, data):
    d = iv[(iv["codneg"] == codneg) & (iv["data"] == data)]
    if d.empty:
        return None
    return d.iloc[0]

# ---------- Black-Scholes p/ marcar contrato que nao negociou ----------
from math import log, sqrt, exp, erf
def _N(x): return 0.5 * (1.0 + erf(x / sqrt(2.0)))
def bs_call(F, K, T, sig, disc):
    if T <= 0 or sig <= 0 or F <= 0 or K <= 0:
        return disc * max(F - K, 0.0)
    d1 = (log(F / K) + 0.5 * sig * sig * T) / (sig * sqrt(T))
    d2 = d1 - sig * sqrt(T)
    return disc * (F * _N(d1) - K * _N(d2))

def carregar_apoio(ticker):
    c = con()
    fw = pd.read_sql('select data,vencimento,forward,desconto from forward_curve '
                     'where ticker_ativo=?', c, params=(ticker,))
    ivd = pd.read_sql('select data,iv_atm_21du,spot from iv_daily where ticker=?',
                      c, params=(ticker,))
    c.close()
    fw["data"] = pd.to_datetime(fw["data"]); fw["venc"] = pd.to_datetime(fw["vencimento"])
    ivd["data"] = pd.to_datetime(ivd["data"])
    return fw.set_index(["data", "venc"]), ivd.set_index("data")

def marcar(iv, fw, ivd, codneg, strike, venc, data):
    """Preco do contrato em 'data'. Usa mercado se negociou; senao BS com a
    IV ATM do dia. Retorna (preco, fonte)."""
    r = preco_em(iv, codneg, data)
    if r is not None:
        return float(r["preco"]), "mercado"
    try:
        F = float(fw.loc[(data, venc), "forward"]); disc = float(fw.loc[(data, venc), "desconto"])
    except KeyError:
        return None, None
    try:
        s = float(ivd.loc[data, "iv_atm_21du"])
    except KeyError:
        return None, None
    if not np.isfinite(F) or not np.isfinite(s) or s <= 0:
        return None, None
    T = max((venc - data).days, 0) / 365.0
    return bs_call(F, strike, T, s, disc if np.isfinite(disc) else 1.0), "modelo"

# ---------- simulacao de um episodio ----------
def simular_episodio(iv, fw, ivd, datas, d_ini, d_fim):
    """Compra call ATM na entrada, rola quando dc<DC_ROLA, vende na saida.
    Retorna lista de pernas (dict) ou None se nao houver call na entrada."""
    dts = [d for d in datas if d_ini <= d <= d_fim]
    if len(dts) < 2:
        return None
    c0 = escolher_call(iv, d_ini, DC_ENTRADA_MIN)
    if c0 is None:
        return None
    pernas = []
    cod, K, venc = c0["codneg"], float(c0["strike"]), c0["venc"]
    p_ent, delta_ent = float(c0["preco"]), float(c0["delta"])
    d_ent = d_ini
    for d in dts[1:]:
        dc = (venc - d).days
        ultimo = (d == dts[-1])
        if dc < DC_ROLA or ultimo:
            p_sai, fonte = marcar(iv, fw, ivd, cod, K, venc, d)
            if p_sai is None:
                if not ultimo:
                    continue   # nao conseguiu rolar hoje; tenta amanha
                # dia de saida sem preco: usa o ultimo preco de mercado
                # disponivel do proprio contrato dentro do episodio.
                h = iv[(iv["codneg"] == cod) & (iv["data"] <= d)
                       & (iv["data"] >= d_ent)]
                if h.empty:
                    return pernas if pernas else None
                p_sai, fonte = float(h.iloc[-1]["preco"]), "ultimo_negociado"
            pernas.append(dict(codneg=cod, strike=K, venc=venc, d_ent=d_ent,
                               d_sai=d, p_ent=p_ent, p_sai=p_sai,
                               delta_ent=delta_ent, fonte_saida=fonte,
                               motivo="saida" if ultimo else "rolagem"))
            if ultimo:
                return pernas
            c1 = escolher_call(iv, d, DC_ENTRADA_MIN)
            if c1 is None:
                return pernas
            cod, K, venc = c1["codneg"], float(c1["strike"]), c1["venc"]
            p_ent, delta_ent = float(c1["preco"]), float(c1["delta"])
            d_ent = d
    return pernas if pernas else None
