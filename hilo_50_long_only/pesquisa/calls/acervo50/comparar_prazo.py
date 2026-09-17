import json, pandas as pd, numpy as np, os, warnings
warnings.filterwarnings("ignore")
from motor5 import simular
G=pd.read_csv("spreads.csv").set_index("ticker")
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
bons=json.load(open("mapa.json"))["bons"]
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
DB="/app/projeto_MIA26/database"; cache={}
def aj(t):
    if t not in cache:
        p=f"{DB}/{t}.xlsx"
        cache[t]=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"] if os.path.exists(p) else None
    return cache[t]

def prep(P):
    d=[]
    for _,x in P.iterrows():
        s=aj(x.ticker)
        try: a=float(s.asof(x.d_ent)); b=float(s.asof(x.d_sai)); d.append(abs((x.s_sai/x.s_ent-1)-(b/a-1)))
        except Exception: d.append(np.nan)
    P=P[~(pd.Series(d,index=P.index).notna()&(pd.Series(d,index=P.index)>0.15))].copy()
    P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
    P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
    P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
    P["r_call"]=P.p_sai/P.p_ent-1; P["r_acao"]=P.s_sai/P.s_ent-1
    return P

def cart(P,spf):
    Wc=[];Wa=[];serie=[]
    Wt={t:1.0 for t in P.ticker.unique()}; Wat=dict(Wt)
    dant={t:INI for t in Wt}; epant={t:None for t in Wt}
    for _,L in P.sort_values("d_sai").iterrows():
        t=L.ticker; sp=spf(t)
        f=(1+CDI_D)**int(max((L.d_ent-dant[t]).days,0)*252/365); Wt[t]*=f; Wat[t]*=f
        liq=L.motivo.startswith("liquidacao")
        rc=((1+L.r_call)*(1.0 if liq else (1-sp))/(1+sp))-1
        n_du=max(int(L.dias*252/365),1)
        Wt[t]*=1+L.w*rc+(1-L.w)*((1+CDI_D)**n_du-1)
        c=(CUSTO_ACAO if L.ep!=epant[t] else 0)+(CUSTO_ACAO if L.motivo.startswith(("saida","liquidacao")) else 0)
        Wat[t]*=1+L.r_acao-c
        dant[t]=L.d_sai; epant[t]=L.ep
        serie.append((L.d_sai,np.mean(list(Wt.values())),np.mean(list(Wat.values()))))
    Sr=pd.DataFrame(serie,columns=["data","call","acao"]).groupby("data").last()
    ddc=(Sr.call/Sr.call.cummax()-1).min()*100
    dda=(Sr.acao/Sr.acao.cummax()-1).min()*100
    return (Sr.call.iloc[-1]**(1/ANOS)-1)*100,(Sr.acao.iloc[-1]**(1/ANOS)-1)*100,ddc,dda

print(f"{'alvo':>6} {'pernas':>7} {'cob':>5} {'dc_ent':>7} {'roladas':>8} {'w':>6} {'mid':>7} {'DD mid':>8} {'p25':>7} {'DD p25':>8} {'mediana':>8}")
for alvo in [None,30,45,60]:
    out=[]
    for t in bons:
        try: p=simular(t,C,S,dc_alvo=alvo)
        except Exception: continue
        if p is not None: out.append(p)
    P=prep(pd.concat(out,ignore_index=True))
    eps=P.groupby(["ticker","ep"]).ngroups
    rol=(P.motivo=="rolagem").sum()/eps
    cm,a,ddc,dda=cart(P,lambda t:0.0)
    cp,_,ddp,_=cart(P,lambda t:G.loc[t,"p25"]/100)
    cme,_,_,_=cart(P,lambda t:G.loc[t,"mediana"]/100)
    rot="v2" if alvo is None else f"{alvo}d"
    print(f"{rot:>6} {len(P):>7} {eps/2390*100:>4.0f}% {P.dc_ent.median():>7.0f} {rol:>8.2f} {P.w.median()*100:>5.1f}% "
          f"{cm:>6.2f}% {ddc:>7.1f}% {cp:>6.2f}% {ddp:>7.1f}% {cme:>7.2f}%")
    if alvo is None: print(f"{'':>6} (acao nas mesmas datas: {a:.2f}% a.a., DD {dda:.1f}% | acao COMPLETA: 14,39%)")
