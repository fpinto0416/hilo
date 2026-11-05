# -*- coding: utf-8 -*-
"""HiLo-50 long-only: acao vs call ATM rolada. Curva diaria por ativo."""
from motor import *
import pandas as pd, numpy as np, sys

CDI_AA = 10.0
CDI_D = (1 + CDI_AA/100)**(1/252) - 1
CUSTO_ACAO = 30/10000          # 30 bps por operacao (mesmo do estudo)
SPREADS = [0.0, 0.02, 0.05, 0.10]   # % do premio, por lado

UNIVERSO = ["PETR4","PETR3","BBDC4","BBAS3","ITUB4","BOVA11","VALE3","SMAL11"]

def serie_premio(iv_cod, fw, ivd, cod, K, venc, dts):
    """Preco diario do contrato nas datas dts. Mercado quando negociou,
    Black-Scholes com a IV ATM do dia quando nao."""
    s = iv_cod.get(cod)
    out, fontes = [], []
    for d in dts:
        p = None
        if s is not None and d in s.index:
            p = float(s.loc[d]); f = "mercado"
        if p is None or not np.isfinite(p) or p <= 0:
            p, f = marcar_bs(fw, ivd, K, venc, d)
        out.append(p); fontes.append(f)
    return out, fontes

def marcar_bs(fw, ivd, K, venc, data):
    try:
        F = float(fw.loc[(data, venc), "forward"]); disc = float(fw.loc[(data, venc), "desconto"])
    except KeyError:
        return None, None
    try:
        sg = float(ivd.loc[data, "iv_atm_21du"])
    except KeyError:
        return None, None
    if not (np.isfinite(F) and np.isfinite(sg) and sg > 0):
        return None, None
    T = max((venc - data).days, 0)/365.0
    return bs_call(F, K, T, sg, disc if np.isfinite(disc) else 1.0), "modelo"

def rodar(t):
    sig = sinal_hilo(t)
    if sig is None: return None
    iv = carregar_opcoes(t)
    if iv is None or iv.empty: return None
    fw, ivd = carregar_apoio(t)
    iv_cod = {c: g.set_index("data")["preco"] for c, g in iv.groupby("codneg")}
    d0 = iv["data"].min()
    sig = sig[sig.index >= d0]
    if len(sig) < 250: return None
    eps = episodios(sig)
    idx = sig.index
    # curvas diarias
    n = len(idx)
    ret_acao = np.zeros(n); ret_prem = np.zeros(n)
    invest = np.zeros(n); marc_mod = 0; marc_tot = 0
    pos = pd.Series(np.arange(n), index=idx)
    pernas_all = []
    eps_ok = 0
    for a, b in eps:
        pr = simular_episodio(iv, fw, ivd, idx, a, b)
        if pr is None: continue
        eps_ok += 1
        for L in pr:
            dts = [d for d in idx if L["d_ent"] <= d <= L["d_sai"]]
            ps, fs = serie_premio(iv_cod, fw, ivd, L["codneg"], L["strike"], L["venc"], dts)
            ps = pd.Series(ps, index=dts).astype(float)
            if ps.isna().any(): ps = ps.ffill().bfill()
            if ps.isna().any() or (ps <= 0).any(): continue
            r = ps.pct_change().fillna(0.0)
            for d, v in r.items(): ret_prem[pos[d]] = v
            marc_mod += sum(1 for x in fs if x == "modelo"); marc_tot += len(fs)
            L["p_serie_ini"], L["p_serie_fim"] = float(ps.iloc[0]), float(ps.iloc[-1])
            pernas_all.append(L)
        # acao no mesmo episodio
        dts = [d for d in idx if a <= d <= b]
        c = sig.loc[dts, "Close"]
        rr = c.pct_change().fillna(0.0)
        for d, v in rr.items(): ret_acao[pos[d]] = v
        for d in dts[1:]: invest[pos[d]] = 1.0
    return dict(ticker=t, idx=idx, ret_acao=ret_acao, ret_prem=ret_prem,
                invest=invest, pernas=pd.DataFrame(pernas_all),
                eps=len(eps), eps_ok=eps_ok,
                frac_modelo=marc_mod/marc_tot if marc_tot else np.nan,
                bh=sig["Close"].pct_change().fillna(0.0).values)

if __name__ == "__main__":
    R = {}
    for t in UNIVERSO:
        try:
            r = rodar(t)
        except Exception as e:
            print(f"{t}: ERRO {e}"); continue
        if r is None: print(f"{t}: sem dado"); continue
        R[t] = r
        print(f"{t}: {r['idx'][0].date()}..{r['idx'][-1].date()} "
              f"episodios {r['eps_ok']}/{r['eps']} pernas {len(r['pernas'])} "
              f"marcacao por modelo {r['frac_modelo']*100:.1f}%")
    import pickle
    pickle.dump(R, open("res.pkl","wb"))
