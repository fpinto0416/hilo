# -*- coding: utf-8 -*-
"""Comparacao correta: mesma linha do tempo, CDI no ocioso dos dois lados,
custo da acao por EPISODIO (nao por perna), so precos de mercado."""
import pickle, numpy as np, pandas as pd
from scipy import stats
from motor import sinal_hilo
pd.set_option("display.width", 260)
R = pickle.load(open("res.pkl","rb"))
CDI_D = (1.10)**(1/252)-1
CUSTO_ACAO = 30/10000
ATIVOS = ["PETR4","BBDC4","BBAS3","ITUB4","VALE3","BOVA11"]

def tabela(t):
    r = R[t]; P = r["pernas"].copy()
    if P.empty: return None
    P = P.sort_values("d_ent").reset_index(drop=True)
    # episodio: nova sequencia comeca depois de uma perna com motivo 'saida'
    ep = [0]
    for i in range(1, len(P)):
        ep.append(ep[-1] + (1 if P.loc[i-1,"motivo"]=="saida" else 0))
    P["ep"] = ep
    S = sinal_hilo(t)["Close"]
    P["s_ent"] = [float(S.loc[d]) if d in S.index else np.nan for d in P.d_ent]
    P["s_sai"] = [float(S.loc[d]) if d in S.index else np.nan for d in P.d_sai]
    P["ativo"] = t
    return P

TS = [x for x in (tabela(t) for t in ATIVOS) if x is not None]
P = pd.concat(TS, ignore_index=True)
# so pernas com as DUAS pontas em preco de mercado
P = P[(P.fonte_saida=="mercado") & P.s_ent.notna() & P.s_sai.notna()].copy()
P["w"] = P.p_ent/(P.delta_ent*P.strike)
P = P[(P.w>0)&(P.w<=1)]
print(f"pernas usadas: {len(P)} | episodios: {P.groupby(['ativo','ep']).ngroups} | "
      f"w mediano: {P.w.median()*100:.1f}% do capital em premio")

def curva(g, spread):
    """Compoe um ativo na ordem cronologica, com CDI entre as pernas."""
    g = g.sort_values("d_ent")
    vc = va = 1.0
    d_ant = None
    ep_ant = None
    for _, L in g.iterrows():
        if d_ant is not None:
            gap = max((L.d_ent - d_ant).days, 0)
            f = (1+CDI_D)**int(gap*252/365)
            vc *= f; va *= f                      # ocioso rende CDI nos dois
        n_du = max(int((L.d_sai-L.d_ent).days*252/365), 1)
        r_call = ((1+ (L.p_sai/L.p_ent-1))*(1-spread)/(1+spread))-1
        vc *= 1 + L.w*r_call + (1-L.w)*((1+CDI_D)**n_du-1)
        r_ac = L.s_sai/L.s_ent - 1
        # custo da acao so na 1a entrada e na ultima saida do episodio
        c = 0.0
        if L.ep != ep_ant: c += CUSTO_ACAO
        if L.motivo == "saida": c += CUSTO_ACAO
        va *= 1 + r_ac - c
        d_ant = L.d_sai; ep_ant = L.ep
    anos = (g.d_sai.max()-g.d_ent.min()).days/365.25
    return (vc**(1/anos)-1)*100, (va**(1/anos)-1)*100, anos

for sp in [0.0, 0.02, 0.05, 0.10]:
    out=[]
    for t,g in P.groupby("ativo"):
        c,a,an = curva(g,sp)
        out.append(dict(ativo=t,n=len(g),anos=round(an,1),call_aa=c,acao_aa=a,dif_pp=c-a))
    o=pd.DataFrame(out)
    print(f"\n===== spread {sp*100:.0f}% do premio por lado =====")
    print(o.round(2).to_string(index=False))
    print(f"  mediana dif: {o.dif_pp.median():+.2f} pp a.a. | ganha em {(o.dif_pp>0).sum()}/{len(o)} ativos")
