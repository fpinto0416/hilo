# -*- coding: utf-8 -*-
"""HiLo 50 long-only com call ATM rolada -- REGRAS v2.

Mudancas em relacao ao motor2:
  1. ATM = strike negociado mais proximo do spot, SEM tolerancia de
     moneyness (antes exigia |ln(K/S)|<=0,06 e descartava 1,7% dos casos).
  3. Vencimento: mensal com >22 dias corridos (era 20), e entre os
     elegiveis escolhe o de MAIOR LIQUIDEZ no strike ATM -- nao o mais
     proximo.
  4. Rolagem quando faltar <10 dias E houver negocio no contrato. Se nao
     conseguir rolar, LEVA A LIQUIDACAO: no vencimento o valor e o
     intrinseco max(S-K,0), que nao depende de haver comprador. Depois da
     liquidacao, se o HiLo ainda indicar compra, entra de novo no mensal
     mais proximo com liquidez.
     Idem na SAIDA: se o contrato nao negociar no dia em que o HiLo zera,
     tenta nos dias seguintes; se chegar ao vencimento, liquida no
     intrinseco.

Isso remove as duas fontes de perda de episodio que nao eram do desenho
da estrategia, e sim da microestrutura: strike fora da tolerancia e
contrato sem comprador na saida.
"""
import numpy as np, pandas as pd
from motor2 import sinal_hilo, episodios, bs_delta, iv_de, CDI_D, CUSTO_ACAO

DC_ENTRADA_MIN = 22
DC_ROLA = 10

def escolher(cal, data, dc_min=DC_ENTRADA_MIN):
    """Call ATM do vencimento mensal com >dc_min dias corridos e MAIOR
    liquidez. Entre os vencimentos elegiveis, escolhe aquele cujo
    candidato ATM teve mais negocios no dia."""
    d = cal.get(data)
    if d is None: return None
    d = d[d.dc > dc_min]
    if d.empty: return None
    melhor = None
    for v in d["venc"].unique():
        dv = d[d["venc"] == v]
        j = dv["money"].abs().idxmin()          # ATM: sem tolerancia
        cand = dv.loc[j]
        if melhor is None or cand["negocios"] > melhor["negocios"]:
            melhor = cand
    return melhor

def _neg(cal, cod, data):
    g = cal.get(data)
    if g is None: return None
    r = g[g.codneg == cod]
    return None if r.empty else r.iloc[0]

def simular(ticker, C, S, ini="2015-01-01", fim="2026-09-09"):
    sig = sinal_hilo(ticker, 50, pd.Timestamp(ini), pd.Timestamp(fim))
    if sig is None or len(sig) < 250: return None
    c = C[C.ticker == ticker]
    if c.empty: return None
    spot = S[S["isin"] == c["isin"].iloc[0]].set_index("data")["spot"]
    c = c.copy(); c["spot"] = c["data"].map(spot)
    c = c[c.spot.notna() & (c.spot > 0) & (c.ultimo > 0)]
    if c.empty: return None
    c["money"] = np.log(c.strike / c.spot)
    cal = {d: g for d, g in c.groupby("data")}
    idx = sig.index
    pernas = []

    def _abrir(d):
        x = escolher(cal, d)
        if x is None: return None
        return dict(cod=x["codneg"], K=float(x["strike"]), venc=x["venc"],
                    p_ent=float(x["ultimo"]), s_ent=float(x["spot"]),
                    d_ent=d, money=float(x["money"]), dc=int(x["dc"]),
                    neg=int(x["negocios"]))

    def _registrar(p, d_sai, p_sai, s_sai, motivo, ep):
        T = max((p["venc"] - p["d_ent"]).days, 1) / 365.0
        iv = iv_de(p["p_ent"], p["s_ent"], p["K"], T)
        dlt = bs_delta(p["s_ent"], p["K"], T, iv) if np.isfinite(iv) else np.nan
        pernas.append(dict(ticker=ticker, codneg=p["cod"], strike=p["K"],
            venc=p["venc"], d_ent=p["d_ent"], d_sai=d_sai, p_ent=p["p_ent"],
            p_sai=p_sai, s_ent=p["s_ent"], s_sai=s_sai, delta=dlt,
            money_ent=p["money"], dc_ent=p["dc"], neg_ent=p["neg"],
            motivo=motivo, ep=ep))

    for a, b in episodios(sig):
        dts = [d for d in idx if a <= d <= b]
        if len(dts) < 2: continue
        pos = None; i = 0
        while i < len(dts):
            d = dts[i]; ultimo_dia = (i == len(dts) - 1)
            if pos is None:
                if ultimo_dia: break
                pos = _abrir(d); i += 1; continue
            # --- venceu: liquida no intrinseco, sem depender de comprador
            if d >= pos["venc"]:
                sv = float(spot.get(pos["venc"], np.nan))
                if not np.isfinite(sv): sv = float(spot.get(d, np.nan))
                if np.isfinite(sv):
                    _registrar(pos, pos["venc"], max(sv - pos["K"], 0.0), sv,
                               "liquidacao", a)
                pos = None
                if not ultimo_dia:            # HiLo ainda comprado: reentra
                    pos = _abrir(d)
                i += 1; continue
            # --- HiLo zerou: vende; se nao negociar, tenta depois, senao liquida
            if ultimo_dia:
                r = _neg(cal, pos["cod"], d)
                if r is not None:
                    _registrar(pos, d, float(r["ultimo"]), float(r["spot"]), "saida", a)
                else:
                    fut = [x for x in idx if d < x <= pos["venc"]]
                    achou = False
                    for x in fut:
                        r2 = _neg(cal, pos["cod"], x)
                        if r2 is not None:
                            _registrar(pos, x, float(r2["ultimo"]), float(r2["spot"]),
                                       "saida_atrasada", a); achou = True; break
                    if not achou:
                        sv = float(spot.get(pos["venc"], np.nan))
                        if np.isfinite(sv):
                            _registrar(pos, pos["venc"], max(sv - pos["K"], 0.0), sv,
                                       "liquidacao_saida", a)
                pos = None; break
            # --- janela de rolagem
            if (pos["venc"] - d).days < DC_ROLA:
                r = _neg(cal, pos["cod"], d)
                if r is not None:
                    _registrar(pos, d, float(r["ultimo"]), float(r["spot"]), "rolagem", a)
                    pos = _abrir(d)
            i += 1
    return pd.DataFrame(pernas) if pernas else None
