"""Drawdown DIARIO da carteira de calls, com o caixa ocioso a CDI.

Ate aqui o DD era medido so quando a perna encerrava, o que esconde a
oscilacao dentro da perna. Aqui a call e marcada pelo ULTIMO negocio de cada
pregao e o caixa rende CDI dia a dia.

  sleeve_t = w * (call_t/p_ent) + (1-w) * (1+cdi)^n_t     (dentro da perna)
  W_t      = W_{t-1} * (1+cdi)                            (fora da perna)

CUIDADO: uma passada sequencial unica. Construir o caminho das pernas e so
depois somar o CDI dos dias vagos perde o CDI acumulado entre pernas (foi
como a primeira versao deu 11,6% a.a. em vez de 17,3%).
"""
import pandas as pd, numpy as np, json, os, warnings
warnings.filterwarnings("ignore")
DB="/app/projeto_MIA26/database"
CDI_D=(1.10)**(1/252)-1; CUSTO_ACAO=30/10000
INI=pd.Timestamp("2015-01-02"); FIM=pd.Timestamp("2026-09-09"); ANOS=(FIM-INI).days/365.25

P=pd.read_parquet("pernas3f.parquet")
P=P[P.delta.notna()&(P.delta>0.05)&(P.delta<0.98)].copy()
P["w"]=P.p_ent/(P.delta*P.s_ent); P=P[(P.w>0)&(P.w<=1)]
P=P.sort_values(["ticker","d_ent"]).reset_index(drop=True)
G=pd.read_csv("spreads.csv").set_index("ticker")

C=pd.read_parquet("calls.parquet")
C=C[C.ultimo>0][["codneg","data","ultimo"]].drop_duplicates(["codneg","data"])
Q={k:v.set_index("data").ultimo.sort_index() for k,v in C.groupby("codneg")}

cal=pd.DatetimeIndex(sorted(pd.read_parquet("spot.parquet").data.unique()))
cal=cal[(cal>=INI)&(cal<=FIM)]; loc={d:i for i,d in enumerate(cal)}; N=len(cal)
_cache={}
def ajust(t):
    if t not in _cache:
        p=f"{DB}/{t}.xlsx"
        if not os.path.exists(p): _cache[t]=None
        else:
            s=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"]
            _cache[t]=s[~s.index.duplicated()].reindex(cal).ffill()
    return _cache[t]

def uma_serie(t, sp, stats):
    """Riqueza diaria do ativo t nas 3 carteiras. Uma passada, sem sobrescrita."""
    aj=ajust(t)
    if aj is None: return None
    L=P[P.ticker==t]
    r=aj.pct_change().fillna(0.0).values
    expo=float((L.w*L.delta).median())

    # sleeve diario de cada perna, indexado por dia
    inicio={}; dentro=np.zeros(N,dtype=bool)
    for _,x in L.iterrows():
        i0,i1=loc.get(x.d_ent),loc.get(x.d_sai)
        if i0 is None or i1 is None or i1<=i0: continue
        jan=cal[i0:i1+1]
        q=Q.get(x.codneg)
        px=q.reindex(jan) if q is not None else pd.Series(np.nan,index=jan)
        stats[0]+=int(px.isna().sum()); stats[1]+=len(jan)
        px=px.ffill(); px.iloc[0]=x.p_ent; px.iloc[-1]=x.p_sai; px=px.ffill().bfill()
        liq=str(x.motivo).startswith("liquidacao")
        rc=px.values*(1.0 if liq else (1-sp))/(x.p_ent*(1+sp))-1
        ndu=np.maximum(((jan-jan[0]).days*252/365).astype(int),0)
        inicio.setdefault(i0,[]).append((i1, x.w*rc+(1-x.w)*((1+CDI_D)**ndu-1)))
        dentro[i0:i1+1]=True

    # episodios (para a acao): da 1a entrada a ultima saida
    ep_ini={}; ep_dentro=np.zeros(N,dtype=bool)
    for ep,g in L.groupby("ep"):
        i0,i1=loc.get(g.d_ent.min()),loc.get(g.d_sai.max())
        if i0 is None or i1 is None or i1<=i0: continue
        ep_ini[i0]=i1; ep_dentro[i0:i1+1]=True

    wc=np.empty(N); wa=np.empty(N); we=np.empty(N)
    Wc=Wa=We=1.0
    base_c=1.0; sl=None; fim_c=-1
    base_a=base_e=1.0; fim_a=-1
    for i in range(N):
        # --- call ---
        if i in inicio:
            for i1,s in inicio[i]:            # rolagem: fecha a anterior e reabre
                if sl is not None and fim_c==i: Wc=base_c*(1+sl[i-sl_i0])
                base_c=Wc; sl,sl_i0,fim_c=s,i,i1
        if sl is not None and sl_i0<=i<=fim_c: Wc=base_c*(1+sl[i-sl_i0])
        elif not dentro[i]: Wc*=1+CDI_D
        wc[i]=Wc
        # --- acao ---
        if i in ep_ini:
            fim_a=ep_ini[i]; Wa*=1-CUSTO_ACAO; We*=1-CUSTO_ACAO*expo
            base_a,base_e=Wa,We
        if i<=fim_a and ep_dentro[i]:
            if i>0 and ep_dentro[i-1] and i not in ep_ini:
                Wa*=1+r[i]; We*=1+expo*r[i]+(1-expo)*CDI_D
            if i==fim_a: Wa*=1-CUSTO_ACAO; We*=1-CUSTO_ACAO*expo
        elif not ep_dentro[i]:
            Wa*=1+CDI_D; We*=1+CDI_D
        wa[i]=Wa; we[i]=We
    return wc,wa,we

def curvas(tickers, spread_fn):
    stats=[0,0]; A={}; B={}; Cc={}
    for t in tickers:
        out=uma_serie(t, spread_fn(t), stats)
        if out is None: continue
        A[t],B[t],Cc[t]=out
    print(f"  dias de perna sem negocio no contrato (ffill): {stats[0]/max(stats[1],1)*100:.1f}%")
    f=lambda D: pd.DataFrame(D,index=cal).mean(axis=1)
    return pd.DataFrame({"call":f(A),"acao":f(B),"acao_expo":f(Cc)})

def dd(x):
    x=np.asarray(x,float); return (x/np.maximum.accumulate(x)-1).min()*100
def resumo(S,rot):
    print(f"\n--- {rot} ---")
    for c,nome in [("call","call+CDI"),("acao","acao 100%"),("acao mesma expo+CDI","acao_expo")][:1]+[("acao","acao 100%"),("acao_expo","acao mesma expo+CDI")]:
        x=S[c].dropna(); r=(x.iloc[-1]**(1/ANOS)-1)*100
        vol=x.pct_change().std()*np.sqrt(252)*100
        print(f"  {nome:22s} {r:+6.2f}% a.a.   DD diario {dd(x):+7.2f}%   vol {vol:5.2f}%   ret/DD {abs(r/dd(x)):5.2f}")

bons=json.load(open("mapa.json"))["bons"]
t50=[t for t in P.ticker.unique() if t in bons]
print(f"=== 50 ATIVOS ({len(t50)}) ===")
S=curvas(t50,lambda t:0.0); resumo(S,"mid-a-mid"); S.to_parquet("curva_mid50.parquet")
S2=curvas(t50,lambda t:G.loc[t,"p25"]/100 if t in G.index else 0.0); resumo(S2,"spread p25 medido")
S2.to_parquet("curva_p2550.parquet")
liq=["PETR4","VALE3","BOVA11"]
print(f"\n=== 3 LIQUIDOS ===")
S3=curvas(liq,lambda t:0.0); resumo(S3,"mid-a-mid"); S3.to_parquet("curva_mid3.parquet")
S4=curvas(liq,lambda t:G.loc[t,"p25"]/100 if t in G.index else 0.0); resumo(S4,"spread p25 medido")
S4.to_parquet("curva_p253.parquet")
