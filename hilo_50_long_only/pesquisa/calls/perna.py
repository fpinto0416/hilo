# -*- coding: utf-8 -*-
"""Teste pareado no nivel da PERNA: call delta-equivalente vs acao,
sobre exatamente as mesmas datas. So usa precos de MERCADO nas duas pontas."""
import pickle, numpy as np, pandas as pd
from scipy import stats
from motor import sinal_hilo
pd.set_option("display.width", 250)
R = pickle.load(open("res.pkl","rb"))
CDI_D = (1.10)**(1/252)-1
BONS = ["PETR4","BBDC4","BBAS3","ITUB4","VALE3","BOVA11"]

linhas = []
for t in BONS:
    r = R[t]; P = r["pernas"].copy()
    if P.empty: continue
    sig = sinal_hilo(t)
    S = sig["Close"]
    P = P[P["fonte_saida"] == "mercado"]           # so saida negociada de fato
    for _, L in P.iterrows():
        try:
            s0, s1 = float(S.loc[L["d_ent"]]), float(S.loc[L["d_sai"]])
        except KeyError:
            continue
        du = (L["d_sai"] - L["d_ent"]).days
        r_call = L["p_sai"]/L["p_ent"] - 1
        r_acao = s1/s0 - 1
        w = L["p_ent"]/(L["delta_ent"]*L["strike"])   # fracao do capital no premio
        if not np.isfinite(w) or w <= 0 or w > 1: continue
        n_du = max(int(du*252/365), 1)
        r_sleeve_call = w*r_call + (1-w)*((1+CDI_D)**n_du - 1)
        r_sleeve_acao = r_acao
        linhas.append(dict(ativo=t, d_ent=L["d_ent"], d_sai=L["d_sai"], dias=du,
                           w=w, delta=L["delta_ent"], r_call=r_call, r_acao=r_acao,
                           sleeve_call=r_sleeve_call, sleeve_acao=r_sleeve_acao,
                           dif=r_sleeve_call-r_sleeve_acao, motivo=L["motivo"]))
D = pd.DataFrame(linhas)
print(f"pernas com as duas pontas em preco de mercado: {len(D)}")
print(f"fracao mediana do capital em premio (w): {D.w.median()*100:.1f}%")
print(f"duracao mediana da perna: {D.dias.median():.0f} dias corridos\n")
print("--- retorno da PERNA (%) ---")
print(D[["r_call","r_acao","sleeve_call","sleeve_acao","dif"]].describe(percentiles=[.1,.25,.5,.75,.9]).round(4).to_string())
t_, p_ = stats.ttest_1samp(D.dif.values, 0)
print(f"\nteste pareado (sleeve call - sleeve acao): media {D.dif.mean()*100:+.3f} pp, "
      f"mediana {D.dif.median()*100:+.3f} pp, t={t_:.2f}, p={p_:.4f}")
print(f"pernas em que a call ganhou da acao: {(D.dif>0).mean()*100:.1f}%")
print("\n--- por ativo ---")
g = D.groupby("ativo").agg(n=("dif","size"), media_dif_pp=("dif",lambda x: x.mean()*100),
                           mediana_dif_pp=("dif",lambda x: x.median()*100),
                           perc_call_ganha=("dif",lambda x:(x>0).mean()*100))
print(g.round(2).to_string())
D.to_csv("pernas.csv", index=False)
