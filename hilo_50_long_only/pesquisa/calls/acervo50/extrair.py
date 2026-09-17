import glob, json, pathlib, pandas as pd, numpy as np
ACERVO=pathlib.Path("/app/acervo_opcoes_b3")
m=json.load(open("mapa.json")); isin_por_ticker=m["isin"]
alvo=set(isin_por_ticker[t] for t in m["bons"])
inv={isin_por_ticker[t]:t for t in m["bons"]}

def eh_mensal(v):
    v=pd.to_datetime(v)
    prim=v-pd.to_timedelta(v.dt.day-1,unit="D")
    desl=(4-prim.dt.weekday)%7
    terc=prim+pd.to_timedelta(desl+14,unit="D")
    return (v-terc).dt.days.abs()<=3

# spot dos ativos alvo
sp=[]
for p in sorted(glob.glob(str(ACERVO/"data/spot/*/*.parquet"))):
    d=pd.read_parquet(p, columns=["data","isin","ultimo"])
    d=d[d["isin"].isin(alvo)]
    if not d.empty: sp.append(d)
S=pd.concat(sp,ignore_index=True); S["data"]=pd.to_datetime(S["data"])
S=S.rename(columns={"ultimo":"spot"}).drop_duplicates(["data","isin"])
S.to_parquet("spot.parquet",index=False)
print(f"spot: {len(S):,} linhas, {S['isin'].nunique()} ativos")

# calls mensais, 5-80 dias corridos, dos ativos alvo
out=[]
for p in sorted(glob.glob(str(ACERVO/"data/opcoes/*/*.parquet"))):
    d=pd.read_parquet(p, columns=["data","codneg","tipo","strike","vencimento",
                                  "medio","ultimo","bid","ask","negocios","fatcot","isin"])
    d=d[(d.tipo=="C") & d["isin"].isin(alvo)]
    if d.empty: continue
    d["data"]=pd.to_datetime(d["data"]); d["venc"]=pd.to_datetime(d["vencimento"],format="%Y%m%d",errors="coerce")
    d["dc"]=(d["venc"]-d["data"]).dt.days
    d=d[d.dc.between(5,80) & eh_mensal(d["venc"])]
    if d.empty: continue
    f=d["fatcot"].replace(0,1).astype(float)
    for c in ["strike","medio","ultimo","bid","ask"]: d[c]=d[c]/f
    out.append(d[["data","codneg","strike","venc","dc","medio","ultimo","bid","ask","negocios","isin"]])
C=pd.concat(out,ignore_index=True)
C["ticker"]=C["isin"].map(inv)
C.to_parquet("calls.parquet",index=False)
print(f"calls: {len(C):,} linhas, {C.ticker.nunique()} ativos, {C.data.min().date()} a {C.data.max().date()}")
