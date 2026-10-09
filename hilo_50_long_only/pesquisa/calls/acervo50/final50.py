import pandas as pd, numpy as np
from scipy import stats
pd.set_option("display.width",260)
P=pd.read_parquet("pernas2.parquet"); G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25

def carteira(spf):
    Wc=[];Wa=[];det=[]
    for t,g in P.groupby("ticker"):
        sp=spf(t)
        g=g.sort_values("d_ent"); vc=va=1.0; d_ant=INI; ep_ant=None
        for _,L in g.iterrows():
            f=(1+CDI_D)**int(max((L.d_ent-d_ant).days,0)*252/365); vc*=f; va*=f
            n_du=max(int(L.dias*252/365),1)
            rc=((1+L.r_call)*(1-sp)/(1+sp))-1
            vc*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n_du-1)
            c=(CUSTO_ACAO if L.ep!=ep_ant else 0)+(CUSTO_ACAO if L.motivo=="saida" else 0)
            va*=1+L.r_acao-c; d_ant=L.d_sai; ep_ant=L.ep
        f=(1+CDI_D)**int(max((FIM-d_ant).days,0)*252/365); vc*=f; va*=f
        Wc.append(vc);Wa.append(va)
        det.append((t,(vc**(1/ANOS)-1)*100,(va**(1/ANOS)-1)*100))
    return (np.mean(Wc)**(1/ANOS)-1)*100,(np.mean(Wa)**(1/ANOS)-1)*100,pd.DataFrame(det,columns=["ticker","call","acao"])

print("=== CARTEIRA equal-weight, 50 ativos, 2015-2026, spread MEDIDO por ativo ===\n")
res=[]
for rot,spf in [("mid-a-mid (0%)",lambda t:0.0),
                ("p25 medido (execucao boa)",lambda t:G.loc[t,"p25"]/100),
                ("mediana medida",lambda t:G.loc[t,"mediana"]/100)]:
    c,a,det=carteira(spf)
    res.append(dict(Execucao=rot,Call_aa=c,Acao_aa=a,Dif_pp=c-a,
                    Ativos_call_ganha=f"{(det.call>det.acao).sum()}/50"))
print(pd.DataFrame(res).round(2).to_string(index=False))

# teste pareado com spread medido por ativo
print("\n=== teste pareado por perna, spread medido por ativo ===")
for rot,col in [("p25",'p25'),("mediana",'mediana')]:
    sp=P.ticker.map(G[col])/100
    rc=((1+P.r_call)*(1-sp)/(1+sp))-1
    n_du=(P.dias*252/365).clip(lower=1).astype(int)
    sc=P.w*rc+(1-P.w)*((1+CDI_D)**n_du-1)
    prim=~P.duplicated(["ticker","ep"]); ult=P.motivo=="saida"
    sa=P.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
    d=(sc-sa).values; t_,p_=stats.ttest_1samp(d,0)
    nb=(d>0).sum(); sg=stats.binomtest(nb,len(d),0.5).pvalue
    print(f"  {rot:>8}: media {d.mean()*100:+.3f} pp  t={t_:+5.2f} p={p_:.4f} | "
          f"call ganha em {nb/len(d)*100:.1f}% (teste do sinal p={sg:.2e})")

# so os 3 liquidos
print("\n=== so PETR4, VALE3, BOVA11 (os unicos com p25 <= 5%) ===")
P3=P[P.ticker.isin(["PETR4","VALE3","BOVA11"])]
print(f"pernas: {len(P3)}")
for rot,col in [("mid",None),("p25",'p25'),("mediana",'mediana')]:
    sp=0.0 if col is None else P3.ticker.map(G[col])/100
    rc=((1+P3.r_call)*(1-sp)/(1+sp))-1
    n_du=(P3.dias*252/365).clip(lower=1).astype(int)
    sc=P3.w*rc+(1-P3.w)*((1+CDI_D)**n_du-1)
    prim=~P3.duplicated(["ticker","ep"]); ult=P3.motivo=="saida"
    sa=P3.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
    d=(sc-sa).values; t_,p_=stats.ttest_1samp(d,0)
    print(f"  {rot:>8}: media {d.mean()*100:+.3f} pp  p={p_:.4f}  call ganha em {(d>0).mean()*100:.1f}%")
