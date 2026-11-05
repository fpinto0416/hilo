# -*- coding: utf-8 -*-
"""HiLo 50 long-only com TRAVA DE ALTA: compra delta ~50, vende delta ~15.

Mesmas regras v2 (motor3) para vencimento, rolagem e liquidacao. O que
muda e a estrutura: em vez de call seca, um spread vertical de mesma
data de vencimento.

Consequencias que o backtest tem que capturar:
- premio LIQUIDO (p_long - p_short) e bem menor que o da call seca, entao
  a mesma exposicao delta custa menos capital;
- o teto (K_short - K_long) TRUNCA o ganho -- e eram justamente as pernas
  de ganho grande que sustentavam o resultado da v2;
- o custo de spread incide sobre as DUAS pernas, em cima de um premio
  liquido menor: o pedagio relativo e maior que na call seca.

Delta nao vem pronto no acervo: e extraido do proprio preco de mercado
via Black-Scholes (IV por bissecao, depois delta).
"""
import numpy as np, pandas as pd
from motor2 import sinal_hilo, episodios, bs_delta, iv_de, CDI_D, CUSTO_ACAO

DC_ENTRADA_MIN = 22
DC_ROLA = 10
DELTA_COMPRA = 0.50
DELTA_VENDA = 0.15
DELTA_TOL_VENDA = 0.12     # aceita venda com delta entre ~0,03 e ~0,27

def _deltas(dv, dias):
    """Delta de cada strike negociado, via IV extraida do preco."""
    T = max(dias, 1)/365.0
    out = []
    for _, r in dv.iterrows():
        iv = iv_de(float(r["ultimo"]), float(r["spot"]), float(r["strike"]), T)
        out.append(bs_delta(float(r["spot"]), float(r["strike"]), T, iv)
                   if np.isfinite(iv) else np.nan)
    return np.array(out)

def escolher_trava(cal, data, dc_min=DC_ENTRADA_MIN):
    """Vencimento mensal >dc_min com mais liquidez no ATM; nele, compra o
    strike de delta mais proximo de 0,50 e vende o de delta mais proximo
    de 0,15. Exige que os dois tenham negociado e que a venda caia dentro
    da tolerancia -- sem isso a 'trava' viraria call seca disfarcada."""
    d = cal.get(data)
    if d is None: return None
    d = d[d.dc > dc_min]
    if d.empty: return None
    melhor = None
    for v in d["venc"].unique():
        dv = d[d["venc"] == v]
        j = dv["money"].abs().idxmin()
        if melhor is None or dv.loc[j,"negocios"] > melhor[1]:
            melhor = (v, dv.loc[j,"negocios"])
    if melhor is None: return None
    dv = d[d["venc"] == melhor[0]].copy()
    if len(dv) < 2: return None
    dv["delta"] = _deltas(dv, int(dv["dc"].iloc[0]))
    dv = dv[dv.delta.notna()]
    if len(dv) < 2: return None
    jl = (dv.delta - DELTA_COMPRA).abs().idxmin()
    L = dv.loc[jl]
    cand = dv[dv.strike > L["strike"]]
    if cand.empty: return None
    js = (cand.delta - DELTA_VENDA).abs().idxmin()
    Sh = cand.loc[js]
    if abs(Sh["delta"] - DELTA_VENDA) > DELTA_TOL_VENDA: return None
    liq = float(L["ultimo"]) - float(Sh["ultimo"])
    if liq <= 0: return None
    return dict(cod_l=L["codneg"], K_l=float(L["strike"]), d_l=float(L["delta"]),
                p_l=float(L["ultimo"]), cod_s=Sh["codneg"], K_s=float(Sh["strike"]),
                d_s=float(Sh["delta"]), p_s=float(Sh["ultimo"]),
                venc=melhor[0], spot=float(L["spot"]), dc=int(L["dc"]),
                neg=int(min(L["negocios"], Sh["negocios"])),
                p_liq=liq, delta_liq=float(L["delta"])-float(Sh["delta"]))

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
    idx = sig.index; pernas = []

    def _reg(p, d_sai, pl, ps, s_sai, motivo, ep):
        pernas.append(dict(ticker=ticker, cod_l=p["cod_l"], cod_s=p["cod_s"],
            K_l=p["K_l"], K_s=p["K_s"], venc=p["venc"], d_ent=p["d_ent"],
            d_sai=d_sai, p_liq_ent=p["p_liq"], p_l_ent=p["p_l"], p_s_ent=p["p_s"],
            p_l_sai=pl, p_s_sai=ps, p_liq_sai=pl-ps, s_ent=p["spot"], s_sai=s_sai,
            delta_liq=p["delta_liq"], d_l=p["d_l"], d_s=p["d_s"],
            dc_ent=p["dc"], neg_ent=p["neg"], teto=p["K_s"]-p["K_l"],
            motivo=motivo, ep=ep))

    for a, b in episodios(sig):
        dts = [d for d in idx if a <= d <= b]
        if len(dts) < 2: continue
        pos = None; i = 0
        while i < len(dts):
            d = dts[i]; fim_ep = (i == len(dts)-1)
            if pos is None:
                if fim_ep: break
                x = escolher_trava(cal, d)
                if x is not None: x["d_ent"] = d; pos = x
                i += 1; continue
            if d >= pos["venc"]:                       # liquidacao
                sv = float(spot.get(pos["venc"], np.nan))
                if not np.isfinite(sv): sv = float(spot.get(d, np.nan))
                if np.isfinite(sv):
                    _reg(pos, pos["venc"], max(sv-pos["K_l"],0.0),
                         max(sv-pos["K_s"],0.0), sv, "liquidacao", a)
                pos = None
                if not fim_ep:
                    x = escolher_trava(cal, d)
                    if x is not None: x["d_ent"] = d; pos = x
                i += 1; continue
            def _fechar(dd):
                rl = _neg(cal, pos["cod_l"], dd); rs = _neg(cal, pos["cod_s"], dd)
                if rl is None or rs is None: return None
                return float(rl["ultimo"]), float(rs["ultimo"]), float(rl["spot"])
            if fim_ep:
                z = _fechar(d)
                if z: _reg(pos, d, z[0], z[1], z[2], "saida", a)
                else:
                    ok = False
                    for x2 in [y for y in idx if d < y <= pos["venc"]]:
                        z2 = _fechar(x2)
                        if z2: _reg(pos, x2, z2[0], z2[1], z2[2], "saida_atrasada", a); ok=True; break
                    if not ok:
                        sv = float(spot.get(pos["venc"], np.nan))
                        if np.isfinite(sv):
                            _reg(pos, pos["venc"], max(sv-pos["K_l"],0.0),
                                 max(sv-pos["K_s"],0.0), sv, "liquidacao_saida", a)
                pos = None; break
            if (pos["venc"] - d).days < DC_ROLA:
                z = _fechar(d)
                if z:
                    _reg(pos, d, z[0], z[1], z[2], "rolagem", a)
                    x = escolher_trava(cal, d)
                    pos = None
                    if x is not None: x["d_ent"] = d; pos = x
            i += 1
    return pd.DataFrame(pernas) if pernas else None
