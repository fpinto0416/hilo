import pandas as pd, numpy as np, json, warnings, os
warnings.filterwarnings("ignore")
from motor2 import sinal_hilo, episodios
CDI_D=(1.10)**(1/252)-1; CUSTO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09")
bons=json.load(open("mapa.json"))["bons"]
P=pd.read_parquet("pernas2.parquet")
S={}; n_ep_tot=0; n_ep_cob=0
for t in bons:
    sig=sinal_hilo(t,50,INI,FIM)
    if sig is None: continue
    eps=episodios(sig); n_ep_tot+=len(eps)
    n_ep_cob+=P[P.ticker==t].groupby("ep").ngroups
    pc=sig["Close"].pct_change().fillna(0.0)
    # DEFASAR: 'long' do dia t vem do Close do dia t, entao a posicao so
    # captura o retorno de t->t+1. Usar inv sem shift e look-ahead (deu
    # 54% a.a. com Sharpe 3,66 e DD de 6% -- impossivel, foi como o bug
    # apareceu).
    inv=sig["long"].shift(1).fillna(0)
    troca=inv.diff().abs().fillna(0)
    S[t]=dict(lo=pc.where(inv>0,0.0)-troca*CUSTO, inv=inv.astype(float), bh=pc)
idx=pd.DataFrame({t:S[t]["lo"] for t in S}).sort_index().index
F={k:pd.DataFrame({t:S[t][k] for t in S}).reindex(idx) for k in ["lo","inv","bh"]}
viv=F["lo"].notna().sum(axis=1).replace(0,np.nan)
ic=(F["inv"].fillna(0).sum(axis=1)/viv).fillna(0).values
pf=lambda k:(F[k].fillna(0).sum(axis=1)/viv).fillna(0).values
def met(r,cdi=False):
    r=np.nan_to_num(np.asarray(r,float))
    if cdi: r=r+(1-ic)*CDI_D
    c=np.cumprod(1+r); n=len(r); sd=r.std(ddof=1)
    return dict(RentAA=(c[-1]**(252/n)-1)*100,Vol=sd*np.sqrt(252)*100,
                Sharpe=r.mean()/sd*np.sqrt(252),DD=(c/np.maximum.accumulate(c)-1).min()*100)
print(f"episodios long totais: {n_ep_tot} | com call negociavel: {n_ep_cob} "
      f"({n_ep_cob/n_ep_tot*100:.0f}%)")
print(f"exposicao media do sinal: {ic.mean()*100:.0f}%\n")
print("HiLo 50 long-only COMPLETO, 50 ativos, 2015-2026 (sem restricao de opcao):")
print(pd.DataFrame([dict(Serie="Acao long-only + CDI",**met(pf("lo"),True)),
                    dict(Serie="BuyAndHold",**met(pf("bh")))]).round(2).to_string(index=False))
