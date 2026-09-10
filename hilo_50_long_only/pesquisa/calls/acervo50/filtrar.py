"""Descarta pernas em que o retorno do spot BRUTO (acervo) diverge do
AJUSTADO -- assinatura de evento societario no meio da perna, em que o
par strike/spot fica inconsistente e o intrinseco sai errado."""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings("ignore")
DB="/app/projeto_MIA26/database"; LIM=0.15
P=pd.read_parquet("pernas3.parquet")
cache={}
def aj(t):
    if t not in cache:
        p=f"{DB}/{t}.xlsx"
        cache[t]=pd.read_excel(p,index_col=0,parse_dates=True).sort_index()["Close"] if os.path.exists(p) else None
    return cache[t]
dif=[]
for _,x in P.iterrows():
    s=aj(x.ticker)
    if s is None: dif.append(np.nan); continue
    try:
        a=float(s.asof(x.d_ent)); b=float(s.asof(x.d_sai))
    except Exception: dif.append(np.nan); continue
    if not (np.isfinite(a) and np.isfinite(b) and a>0): dif.append(np.nan); continue
    dif.append(abs((x.s_sai/x.s_ent-1)-(b/a-1)))
P["dif_ajuste"]=dif
mask=P.dif_ajuste.notna()&(P.dif_ajuste>LIM)
print(f"pernas: {len(P)} | descartadas por evento societario: {mask.sum()} ({mask.mean()*100:.1f}%)")
print(P[mask].groupby("ticker").size().sort_values(ascending=False).head(10).to_string())
P[~mask].drop(columns=["dif_ajuste"]).to_parquet("pernas3f.parquet",index=False)
print(f"\ngravado pernas3f.parquet com {(~mask).sum()} pernas")
