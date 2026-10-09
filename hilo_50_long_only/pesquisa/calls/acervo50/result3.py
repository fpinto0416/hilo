import pandas as pd, numpy as np
from scipy import stats
pd.set_option("display.width",260)
P=pd.read_parquet("pernas3f.parquet"); G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
P["w"]=P.p_ent/(P.delta*P.s_ent)
P=P[(P.w>0)&(P.w<=1)]
P["r_call"]=P.p_sai/P.p_ent-1
P["r_acao"]=P.s_sai/P.s_ent-1
print(f"pernas usadas: {len(P):,} | ativos {P.ticker.nunique()} | w mediano {P.w.median()*100:.1f}%")
print(f"retorno por perna: mediana {P.r_call.median()*100:+.1f}%  media {P.r_call.mean()*100:+.1f}%")
print("\nretorno medio por tipo de saida:")
print(P.groupby("motivo").r_call.agg(n="size",mediana=lambda x:x.median()*100,media=lambda x:x.mean()*100).round(1).to_string())

def carteira(spf):
    Wc=[];Wa=[];det=[]
    for t,g in P.groupby("ticker"):
        sp=spf(t); g=g.sort_values("d_ent"); vc=va=1.0; d_ant=INI; ep_ant=None
        for _,L in g.iterrows():
            f=(1+CDI_D)**int(max((L.d_ent-d_ant).days,0)*252/365); vc*=f; va*=f
            n_du=max(int(L.dias*252/365),1)
            # liquidacao no vencimento nao paga spread: nao ha venda
            liq = L.motivo.startswith("liquidacao")
            rc=((1+L.r_call)*(1.0 if liq else (1-sp))/(1+sp))-1
            vc*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n_du-1)
            c=(CUSTO_ACAO if L.ep!=ep_ant else 0)+(CUSTO_ACAO if L.motivo.startswith("saida") or liq else 0)
            va*=1+L.r_acao-c; d_ant=L.d_sai; ep_ant=L.ep
        f=(1+CDI_D)**int(max((FIM-d_ant).days,0)*252/365); vc*=f; va*=f
        Wc.append(vc);Wa.append(va); det.append((t,(vc**(1/ANOS)-1)*100,(va**(1/ANOS)-1)*100))
    return (np.mean(Wc)**(1/ANOS)-1)*100,(np.mean(Wa)**(1/ANOS)-1)*100,pd.DataFrame(det,columns=["ticker","call","acao"])

print("\n=== CARTEIRA equal-weight, 50 ativos, 2015-2026 (regras v2) ===")
res=[]
for rot,spf in [("mid-a-mid (0%)",lambda t:0.0),
                ("p25 medido",lambda t:G.loc[t,"p25"]/100),
                ("mediana medida",lambda t:G.loc[t,"mediana"]/100)]:
    c,a,det=carteira(spf)
    res.append(dict(Execucao=rot,Call_aa=c,Acao_aa=a,Dif_pp=c-a,Ganha=f"{(det.call>det.acao).sum()}/50"))
print(pd.DataFrame(res).round(2).to_string(index=False))
print("\nBaseline: acao long-only COMPLETA (sem exigir call) = 14,39% a.a.")
c0,_,det0=carteira(lambda t:0.0)
print(f"call a mid-a-mid = {c0:.2f}% a.a.  ->  {'GANHA' if c0>14.39 else 'perde'} do baseline")
print("\n=== so PETR4/VALE3/BOVA11 ===")
P3=P[P.ticker.isin(["PETR4","VALE3","BOVA11"])]
for rot,col in [("mid",None),("p25",'p25'),("mediana",'mediana')]:
    sp=0.0 if col is None else P3.ticker.map(G[col])/100
    liq=P3.motivo.str.startswith("liquidacao")
    rc=((1+P3.r_call)*np.where(liq,1.0,(1-sp))/(1+sp))-1
    n_du=(P3.dias*252/365).clip(lower=1).astype(int)
    sc=P3.w*rc+(1-P3.w)*((1+CDI_D)**n_du-1)
    prim=~P3.duplicated(["ticker","ep"]); ult=P3.motivo.str.startswith(("saida","liquidacao"))
    sa=P3.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
    d=(sc-sa).values; t_,p_=stats.ttest_1samp(d,0)
    print(f"  {rot:>8}: media {d.mean()*100:+.3f} pp  p={p_:.4f}  call ganha em {(d>0).mean()*100:.1f}%")
