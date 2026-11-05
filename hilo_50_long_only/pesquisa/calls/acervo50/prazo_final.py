# -*- coding: utf-8 -*-
"""Qual o melhor prazo de vencimento? Grade estendida ate 180 dias.

A comparacao anterior (comparar_prazo.py) parou em 60d -- e 60d venceu.
Otimo na BORDA da grade nao e otimo: pode so nao ter sido testado o
suficiente. Aqui a grade vai a 180d, e o drawdown e o DIARIO (marcado a
mercado), nao o de resolucao de perna, que favorece a call (ver 12.14).
"""
import json, os, warnings, pandas as pd, numpy as np
warnings.filterwarnings("ignore")
from motor5 import simular
G=pd.read_csv("spreads.csv").set_index("ticker")
C=pd.read_parquet("calls.parquet"); S=pd.read_parquet("spot.parquet")
bons=json.load(open("mapa.json"))["bons"]
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25
DB="/app/projeto_MIA26/database"
cal=pd.DatetimeIndex(sorted(S.data.unique())); cal=cal[(cal>=INI)&(cal<=FIM)]
loc={d:i for i,d in enumerate(cal)}; N=len(cal)
_aj={}
def aj(t):
    if t not in _aj:
        p=f"{DB}/{t}.xlsx"
        if not os.path.exists(p): _aj[t]=None
        else:
            s=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"]
            _aj[t]=s[~s.index.duplicated()].reindex(cal).ffill()
    return _aj[t]
Cq=C[C.ultimo>0][["codneg","data","ultimo"]].drop_duplicates(["codneg","data"])
Q={k:v.set_index("data").ultimo.sort_index() for k,v in Cq.groupby("codneg")}

def prep(P):
    d=[]
    for _,x in P.iterrows():
        s=aj(x.ticker)
        try: a=float(s.asof(x.d_ent)); b=float(s.asof(x.d_sai)); d.append(abs((x.s_sai/x.s_ent-1)-(b/a-1)))
        except Exception: d.append(np.nan)
    d=pd.Series(d,index=P.index)
    P=P[~(d.notna()&(d>0.15))].copy()
    P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
    P["dias"]=(P.d_sai-P.d_ent).dt.days.clip(lower=1)
    P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
    P["r_call"]=P.p_sai/P.p_ent-1; P["r_acao"]=P.s_sai/P.s_ent-1
    return P.sort_values(["ticker","d_ent"]).reset_index(drop=True)

def serie_diaria(P,tickers,spf,stats):
    """Riqueza diaria da call (marcada a mercado) e da acao. Passada unica:
    montar as pernas e so depois somar CDI dos dias vagos perde o CDI
    entre pernas (ver 12.14)."""
    A={};B={}
    for t in tickers:
        a=aj(t)
        if a is None: continue
        sp=spf(t); L=P[P.ticker==t]
        if L.empty: continue
        r=a.pct_change().fillna(0.0).values
        inicio={}; dentro=np.zeros(N,bool)
        for _,x in L.iterrows():
            i0,i1=loc.get(x.d_ent),loc.get(x.d_sai)
            if i0 is None or i1 is None or i1<=i0: continue
            jan=cal[i0:i1+1]; q=Q.get(x.cod if "cod" in L.columns else x.codneg)
            px=q.reindex(jan) if q is not None else pd.Series(np.nan,index=jan)
            stats[0]+=int(px.isna().sum()); stats[1]+=len(jan)
            px=px.ffill(); px.iloc[0]=x.p_ent; px.iloc[-1]=x.p_sai; px=px.ffill().bfill()
            liq=str(x.motivo).startswith("liquidacao")
            rc=px.values*(1.0 if liq else (1-sp))/(x.p_ent*(1+sp))-1
            ndu=np.maximum(((jan-jan[0]).days*252/365).astype(int),0)
            inicio.setdefault(i0,[]).append((i1,x.w*rc+(1-x.w)*((1+CDI_D)**ndu-1)))
            dentro[i0:i1+1]=True
        ep_ini={}; ep_d=np.zeros(N,bool)
        for ep,g in L.groupby("ep"):
            i0,i1=loc.get(g.d_ent.min()),loc.get(g.d_sai.max())
            if i0 is None or i1 is None or i1<=i0: continue
            ep_ini[i0]=i1; ep_d[i0:i1+1]=True
        wc=np.empty(N); wa=np.empty(N); Wc=Wa=1.0
        base=1.0; sl=None; sl_i0=0; fim=-1; fim_a=-1
        for i in range(N):
            if i in inicio:
                for i1,s in inicio[i]:
                    if sl is not None and fim==i: Wc=base*(1+sl[i-sl_i0])
                    base=Wc; sl,sl_i0,fim=s,i,i1
            if sl is not None and sl_i0<=i<=fim: Wc=base*(1+sl[i-sl_i0])
            elif not dentro[i]: Wc*=1+CDI_D
            wc[i]=Wc
            if i in ep_ini: fim_a=ep_ini[i]; Wa*=1-CUSTO_ACAO
            if i<=fim_a and ep_d[i]:
                if i>0 and ep_d[i-1] and i not in ep_ini: Wa*=1+r[i]
                if i==fim_a: Wa*=1-CUSTO_ACAO
            elif not ep_d[i]: Wa*=1+CDI_D
            wa[i]=Wa
        A[t]=wc; B[t]=wa
    f=lambda D: pd.DataFrame(D,index=cal).mean(axis=1)
    return f(A),f(B)

def dd(x): x=np.asarray(x,float); return (x/np.maximum.accumulate(x)-1).min()*100
def aa(x): return (x.iloc[-1]**(1/ANOS)-1)*100

GRADE=[None,30,45,60,90,120,180]
print(f"{'alvo':>5} {'pernas':>7} {'cob':>5} {'dc':>4} {'rol/ep':>7} {'w':>6} "
      f"{'mid':>7} {'DDd mid':>8} {'p25':>7} {'DDd p25':>8} {'med':>7} {'ffill':>6}")
res={}
for alvo in GRADE:
    out=[]
    for t in bons:
        try: p=simular(t,C,S,dc_alvo=alvo)
        except Exception: continue
        if p is not None: out.append(p)
    if not out: continue
    P=prep(pd.concat(out,ignore_index=True))
    eps=P.groupby(["ticker","ep"]).ngroups
    rol=(P.motivo=="rolagem").sum()/max(eps,1)
    st=[0,0]
    cm,am=serie_diaria(P,bons,lambda t:0.0,st)
    cp,_=serie_diaria(P,bons,lambda t:G.loc[t,"p25"]/100 if t in G.index else 0.0,[0,0])
    cme,_=serie_diaria(P,bons,lambda t:G.loc[t,"mediana"]/100 if t in G.index else 0.0,[0,0])
    rot="v2" if alvo is None else f"{alvo}d"
    res[rot]=dict(P=P,mid=aa(cm),ddmid=dd(cm),p25=aa(cp),ddp25=dd(cp),med=aa(cme),acao=aa(am),ddacao=dd(am))
    print(f"{rot:>5} {len(P):>7} {eps/2390*100:>4.0f}% {P.dc_ent.median():>4.0f} {rol:>7.2f} {P.w.median()*100:>5.1f}% "
          f"{aa(cm):>6.2f}% {dd(cm):>7.1f}% {aa(cp):>6.2f}% {dd(cp):>7.1f}% {aa(cme):>6.2f}% {st[0]/max(st[1],1)*100:>5.1f}%")
    if alvo is None:
        print(f"{'':>5} acao nas mesmas datas: {aa(am):.2f}% a.a. DD {dd(am):.1f}% | acao COMPLETA 14,39%")
import pickle; pickle.dump({k:{i:j for i,j in v.items() if i!='P'} for k,v in res.items()},open("prazo_final.pkl","wb"))
