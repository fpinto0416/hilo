# -*- coding: utf-8 -*-
"""Call - acao por ativo, no prazo alvo de 60 dias, para os 6 do painel.

A tabela do artefato usava o prazo v2 (>20d, mais liquido). Ao trocar a
sugestao para ~60d a coluna 'call - acao' tem que ser refeita no MESMO
prazo, senao mistura regra nova com numero velho.
"""
import os, warnings, pandas as pd, numpy as np
warnings.filterwarnings("ignore")
from motor5 import simular
SEIS=["PETR4","VALE3","BOVA11","BBDC4","BBAS3","ITUB4"]
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
DB="/app/projeto_MIA26/database"
def aj(t):
    p=f"{DB}/{t}.xlsx"
    return pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"] if os.path.exists(p) else None

def prep(P,t):
    s=aj(t); d=[]
    for _,x in P.iterrows():
        try: a=float(s.asof(x.d_ent)); b=float(s.asof(x.d_sai)); d.append(abs((x.s_sai/x.s_ent-1)-(b/a-1)))
        except Exception: d.append(np.nan)
    d=pd.Series(d,index=P.index); P=P[~(d.notna()&(d>0.15))].copy()
    P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
    P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
    P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
    P["r_call"]=P.p_sai/P.p_ent-1; P["r_acao"]=P.s_sai/P.s_ent-1
    return P.sort_values("d_ent")

def aa(P,sp):
    Wc=Wa=1.0; dant=INI; epant=None
    for _,L in P.iterrows():
        f=(1+CDI_D)**int(max((L.d_ent-dant).days,0)*252/365); Wc*=f; Wa*=f
        liq=L.motivo.startswith("liquidacao")
        rc=((1+L.r_call)*(1.0 if liq else (1-sp))/(1+sp))-1
        n=max(int(L.dias*252/365),1)
        Wc*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n-1)
        c=(CUSTO if L.ep!=epant else 0)+(CUSTO if L.motivo.startswith(("saida","liquidacao")) else 0)
        Wa*=1+L.r_acao-c
        dant=L.d_sai; epant=L.ep
    return (Wc**(1/ANOS)-1)*100,(Wa**(1/ANOS)-1)*100

print(f"{'ticker':>7} {'alvo':>5} {'pernas':>7} {'rol/ep':>7} {'dc':>4} {'spread':>7} "
      f"{'call':>7} {'acao':>7} {'dif':>8} {'dif mid':>8}")
for t in SEIS:
    sp=G.loc[t,"p25"]/100 if t in G.index else np.nan
    tip=G.loc[t,"mediana"]/100 if t in G.index else np.nan
    for alvo,rot in [(None,"v2"),(60,"60d")]:
        p=simular(t,C,S,dc_alvo=alvo)
        if p is None: continue
        P=prep(p,t); eps=P.ep.nunique()
        rol=(P.motivo=="rolagem").sum()/max(eps,1)
        c_t,a_t=aa(P,tip)     # spread tipico (mediana) = o que a tabela mostra
        c_m,a_m=aa(P,0.0)
        print(f"{t:>7} {rot:>5} {len(P):>7} {rol:>7.2f} {P.dc_ent.median():>4.0f} {tip*100:>6.1f}% "
              f"{c_t:>6.2f}% {a_t:>6.2f}% {c_t-a_t:>+7.2f} {c_m-a_m:>+7.2f}")
