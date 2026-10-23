# -*- coding: utf-8 -*-
"""Call seca com PRAZO ALVO parametrizado.

Motivacao: o pedagio de spread e proporcional ao numero de rolagens.
Comprar prazo mais longo reduz rolagens -- mas sobe o premio (mais
capital em risco por perna, w maior) e a liquidez de vencimento longo na
B3 e pior (spread maior, cobertura menor). E empirico.

DC_ALVO=None reproduz a regra v2 (mais liquido entre os elegiveis).
"""
import numpy as np, pandas as pd
from motor2 import sinal_hilo, episodios, bs_delta, iv_de

DC_MIN = 22
DC_ROLA = 10

def escolher(cal, data, dc_alvo=None, dc_min=DC_MIN):
    d = cal.get(data)
    if d is None: return None
    d = d[d.dc > dc_min]
    if d.empty: return None
    melhor = None
    for v in d["venc"].unique():
        dv = d[d["venc"] == v]
        j = dv["money"].abs().idxmin()
        cand = dv.loc[j]
        if dc_alvo is None:
            score = cand["negocios"]              # v2: mais liquido
            if melhor is None or score > melhor[1]: melhor = (cand, score)
        else:
            score = -abs(int(cand["dc"]) - dc_alvo)   # prazo mais proximo do alvo
            if melhor is None or score > melhor[1]: melhor = (cand, score)
    return None if melhor is None else melhor[0]

def _neg(cal, cod, data):
    g = cal.get(data)
    if g is None: return None
    r = g[g.codneg == cod]
    return None if r.empty else r.iloc[0]

def simular(ticker, C, S, dc_alvo=None, ini="2015-01-01", fim="2026-09-09"):
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
    idx = sig.index; pernas = []
    def _abrir(d):
        x = escolher(cal, d, dc_alvo)
        if x is None: return None
        return dict(cod=x["codneg"], K=float(x["strike"]), venc=x["venc"],
                    p_ent=float(x["ultimo"]), s_ent=float(x["spot"]), d_ent=d,
                    money=float(x["money"]), dc=int(x["dc"]), neg=int(x["negocios"]))
    def _reg(p, d_sai, p_sai, s_sai, motivo, ep):
        T = max((p["venc"]-p["d_ent"]).days,1)/365.0
        iv = iv_de(p["p_ent"], p["s_ent"], p["K"], T)
        dlt = bs_delta(p["s_ent"], p["K"], T, iv) if np.isfinite(iv) else np.nan
        pernas.append(dict(ticker=ticker, codneg=p["cod"], strike=p["K"], venc=p["venc"],
            d_ent=p["d_ent"], d_sai=d_sai, p_ent=p["p_ent"], p_sai=p_sai,
            s_ent=p["s_ent"], s_sai=s_sai, delta=dlt, money_ent=p["money"],
            dc_ent=p["dc"], neg_ent=p["neg"], motivo=motivo, ep=ep))
    for a, b in episodios(sig):
        dts = [d for d in idx if a <= d <= b]
        if len(dts) < 2: continue
        pos=None; i=0
        while i < len(dts):
            d=dts[i]; fim_ep=(i==len(dts)-1)
            if pos is None:
                if fim_ep: break
                pos=_abrir(d); i+=1; continue
            if d >= pos["venc"]:
                sv=float(spot.get(pos["venc"],np.nan))
                if not np.isfinite(sv): sv=float(spot.get(d,np.nan))
                if np.isfinite(sv): _reg(pos,pos["venc"],max(sv-pos["K"],0.0),sv,"liquidacao",a)
                pos=None
                if not fim_ep: pos=_abrir(d)
                i+=1; continue
            if fim_ep:
                r=_neg(cal,pos["cod"],d)
                if r is not None: _reg(pos,d,float(r["ultimo"]),float(r["spot"]),"saida",a)
                else:
                    ok=False
                    for x2 in [y for y in idx if d<y<=pos["venc"]]:
                        r2=_neg(cal,pos["cod"],x2)
                        if r2 is not None: _reg(pos,x2,float(r2["ultimo"]),float(r2["spot"]),"saida_atrasada",a); ok=True; break
                    if not ok:
                        sv=float(spot.get(pos["venc"],np.nan))
                        if np.isfinite(sv): _reg(pos,pos["venc"],max(sv-pos["K"],0.0),sv,"liquidacao_saida",a)
                pos=None; break
            if (pos["venc"]-d).days < DC_ROLA:
                r=_neg(cal,pos["cod"],d)
                if r is not None:
                    _reg(pos,d,float(r["ultimo"]),float(r["spot"]),"rolagem",a)
                    pos=_abrir(d)
            i+=1
    return pd.DataFrame(pernas) if pernas else None
