# -*- coding: utf-8 -*-
"""HiLo 50 long-only: call ATM rolada vs acao, sobre o acervo-opcoes-b3.

Diferencas em relacao a versao antiga (que rodava sobre vol_implicita.db):
- 50 ativos em vez de 6;
- o acervo nao traz delta nem forward, entao o delta sai de Black-Scholes
  com a IV extraida do proprio preco de mercado;
- ATM por |ln(K/spot)|, com tolerancia -- em dia ralo o strike mais
  proximo ENTRE OS QUE NEGOCIARAM pode estar longe do dinheiro.
"""
import numpy as np, pandas as pd
from math import log, sqrt, exp, erf

DB_ACAO="/app/projeto_MIA26/database"
CDI_AA=10.0; CDI_D=(1+CDI_AA/100)**(1/252)-1; R_FREE=np.log(1+CDI_AA/100)
CUSTO_ACAO=30/10000
DC_ENTRADA_MIN=20; DC_ROLA=10; TOL_MONEY=0.06

def _N(x): return 0.5*(1.0+erf(x/sqrt(2.0)))
def bs_call(S,K,T,sig,r=R_FREE):
    if T<=0 or sig<=0: return max(S-K,0.0)
    d1=(log(S/K)+(r+0.5*sig*sig)*T)/(sig*sqrt(T))
    return S*_N(d1)-K*exp(-r*T)*_N(d1-sig*sqrt(T))
def bs_delta(S,K,T,sig,r=R_FREE):
    if T<=0 or sig<=0: return 1.0 if S>K else 0.0
    return _N((log(S/K)+(r+0.5*sig*sig)*T)/(sig*sqrt(T)))
def iv_de(preco,S,K,T):
    """IV por bissecao. Devolve NaN se o preco estiver fora do range do modelo."""
    if T<=0 or preco<=0: return np.nan
    lo,hi=1e-4,5.0
    if preco<=bs_call(S,K,T,lo) or preco>=bs_call(S,K,T,hi): return np.nan
    for _ in range(60):
        mid=(lo+hi)/2
        if bs_call(S,K,T,mid)<preco: lo=mid
        else: hi=mid
    return (lo+hi)/2

def sinal_hilo(ticker,n=50,ini=None,fim=None):
    import os
    p=f"{DB_ACAO}/{ticker}.xlsx"
    if not os.path.exists(p): return None
    d=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()
    d=d.dropna(subset=["Open","High","Low","Close"]); d=d[~d.index.duplicated(keep="first")]
    d["hi"]=d["High"].rolling(n).mean().shift(1); d["lo"]=d["Low"].rolling(n).mean().shift(1)
    s=np.where(d["Close"]>d["hi"],1,np.where(d["Close"]<d["lo"],-1,0))
    d["long"]=(pd.Series(s,index=d.index).replace(0,np.nan).ffill().fillna(0)>0).astype(int)
    if ini is not None: d=d[d.index>=ini]
    if fim is not None: d=d[d.index<=fim]
    return d[["Close","long"]]

def episodios(sig):
    L=sig["long"].values; idx=sig.index; eps=[]; i=0
    while i<len(L):
        if L[i]==1 and (i==0 or L[i-1]==0):
            j=i
            while j+1<len(L) and L[j+1]==1: j+=1
            eps.append((idx[i], idx[j+1] if j+1<len(L) else idx[j])); i=j+1
        else: i+=1
    return eps

def escolher(cal,data,dc_min=DC_ENTRADA_MIN,tol=TOL_MONEY):
    """Call ATM do 1o vencimento mensal com mais de dc_min dias corridos."""
    d=cal.get(data)
    if d is None: return None
    d=d[d.dc>dc_min]
    if d.empty: return None
    for v in sorted(d["venc"].unique()):
        dv=d[d["venc"]==v]
        j=dv["money"].abs().idxmin()
        if abs(dv.loc[j,"money"])<=tol: return dv.loc[j]
    return None

def simular(ticker, C, S, ini="2015-01-01", fim="2026-09-09"):
    """Uma linha por PERNA (compra e venda de uma call), com preco de
    mercado nas duas pontas. Retorna None se nao houver dado."""
    sig=sinal_hilo(ticker,50,pd.Timestamp(ini),pd.Timestamp(fim))
    if sig is None or len(sig)<250: return None
    c=C[C.ticker==ticker]
    if c.empty: return None
    sp=S[S["isin"]==c["isin"].iloc[0]].set_index("data")["spot"]
    c=c.copy(); c["spot"]=c["data"].map(sp)
    # PRECO = 'ultimo' (ultimo negocio do dia), nao 'medio' (VWAP do dia).
    # O sinal do HiLo so e conhecido no FECHAMENTO, e a acao entra pelo
    # fechamento; comprar a opcao pelo VWAP do dia seria look-ahead --
    # em dia de alta o VWAP fica abaixo do fechamento, barateando a call
    # de graca. 'ultimo' e o preco consistente com o sinal.
    c=c[c.spot.notna() & (c.spot>0) & (c.ultimo>0)]
    if c.empty: return None
    c["money"]=np.log(c.strike/c.spot)
    cal={d:g for d,g in c.groupby("data")}
    idx=sig.index; pernas=[]
    for a,b in episodios(sig):
        dts=[d for d in idx if a<=d<=b]
        if len(dts)<2: continue
        c0=escolher(cal,a)
        if c0 is None: continue
        cod,K,venc=c0["codneg"],float(c0["strike"]),c0["venc"]
        p_ent,s_ent,d_ent=float(c0["ultimo"]),float(c0["spot"]),a
        for k,d in enumerate(dts[1:],1):
            ultimo=(k==len(dts)-1)
            if (venc-d).days<DC_ROLA or ultimo:
                g=cal.get(d)
                if g is None: continue
                r=g[g.codneg==cod]
                if r.empty: continue          # nao negociou hoje: tenta amanha
                r=r.iloc[0]
                T=max((venc-d_ent).days,1)/365.0
                sig_iv=iv_de(p_ent,s_ent,K,T)
                dlt=bs_delta(s_ent,K,T,sig_iv) if np.isfinite(sig_iv) else np.nan
                pernas.append(dict(ticker=ticker,codneg=cod,strike=K,venc=venc,
                    d_ent=d_ent,d_sai=d,p_ent=p_ent,p_sai=float(r["ultimo"]),
                    s_ent=s_ent,s_sai=float(r["spot"]),delta=dlt,
                    money_ent=float(c0["money"]) if k==1 else np.nan,
                    dc_ent=int(c0["dc"]) if k==1 else np.nan,
                    motivo="saida" if ultimo else "rolagem", ep=a))
                if ultimo: break
                c1=escolher(cal,d)
                if c1 is None: break
                cod,K,venc=c1["codneg"],float(c1["strike"]),c1["venc"]
                p_ent,s_ent,d_ent=float(c1["ultimo"]),float(c1["spot"]),d
    return pd.DataFrame(pernas) if pernas else None
