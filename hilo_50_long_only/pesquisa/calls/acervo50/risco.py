import pandas as pd, numpy as np
pd.set_option("display.width",260)
P=pd.read_parquet("pernas3f.parquet"); G=pd.read_csv("spreads.csv").set_index("ticker")
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
P["r_call"]=P.p_sai/P.p_ent-1; P["r_acao"]=P.s_sai/P.s_ent-1

def sleeves(sp_fn):
    sp=P.ticker.map(lambda t: sp_fn(t))
    liq=P.motivo.str.startswith("liquidacao")
    rc=((1+P.r_call)*np.where(liq,1.0,(1-sp))/(1+sp))-1
    n_du=(P.dias*252/365).clip(lower=1).astype(int)
    sc=P.w*rc+(1-P.w)*((1+CDI_D)**n_du-1)
    prim=~P.duplicated(["ticker","ep"]); ult=P.motivo.str.startswith(("saida","liquidacao"))
    sa=P.r_acao-CUSTO_ACAO*(prim.astype(float)+ult.astype(float))
    return sc,sa

print("=== 1. RISCO POR OPERACAO (retorno do sleeve numa perna) ===\n")
sc,sa=sleeves(lambda t:0.0)
D=pd.DataFrame({"call":sc,"acao":sa})
print(D.describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).mul(100).round(2).to_string())
print(f"\npior perna:      call {D.call.min()*100:+.1f}%   acao {D.acao.min()*100:+.1f}%")
print(f"perdas > 10%:    call {(D.call<-0.10).mean()*100:.1f}%    acao {(D.acao<-0.10).mean()*100:.1f}%")
print(f"perdas > 20%:    call {(D.call<-0.20).mean()*100:.1f}%    acao {(D.acao<-0.20).mean()*100:.1f}%")
print(f"\nperda maxima teorica por perna = w (premio integral) = mediana {P.w.median()*100:.1f}%")

print("\n\n=== 2. DRAWDOWN DA CARTEIRA (encadeando as pernas, equal-weight) ===\n")
def curva_carteira(sp_fn):
    """Riqueza da carteira em resolucao de PERNA (nao diaria). Cada ativo
    encadeia suas pernas com CDI no ocioso; a carteira e a media dos 50."""
    datas=sorted(P.d_sai.unique())
    W={t:1.0 for t in P.ticker.unique()}; dant={t:INI for t in W}; epant={t:None for t in W}
    Wa=dict(W); danta=dict(dant)
    serie=[]
    for _,L in P.sort_values("d_sai").iterrows():
        t=L.ticker; sp=sp_fn(t)
        f=(1+CDI_D)**int(max((L.d_ent-dant[t]).days,0)*252/365)
        W[t]*=f; Wa[t]*=f
        liq=L.motivo.startswith("liquidacao")
        rc=((1+L.r_call)*(1.0 if liq else (1-sp))/(1+sp))-1
        n_du=max(int(L.dias*252/365),1)
        W[t]*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n_du-1)
        c=(CUSTO_ACAO if L.ep!=epant[t] else 0)+(CUSTO_ACAO if L.motivo.startswith(("saida","liquidacao")) else 0)
        Wa[t]*=1+L.r_acao-c
        dant[t]=L.d_sai; epant[t]=L.ep
        serie.append((L.d_sai, np.mean(list(W.values())), np.mean(list(Wa.values()))))
    S=pd.DataFrame(serie,columns=["data","call","acao"]).groupby("data").last()
    return S
def dd(x): 
    x=np.asarray(x); return (x/np.maximum.accumulate(x)-1).min()*100
for rot,fn in [("mid-a-mid",lambda t:0.0),("p25 medido",lambda t:G.loc[t,"p25"]/100)]:
    S=curva_carteira(fn)
    print(f"{rot}:  drawdown call {dd(S.call):+.2f}%   drawdown acao {dd(S.acao):+.2f}%")
    print(f"            rent a.a. call {(S.call.iloc[-1]**(1/ANOS)-1)*100:+.2f}%   acao {(S.acao.iloc[-1]**(1/ANOS)-1)*100:+.2f}%")
